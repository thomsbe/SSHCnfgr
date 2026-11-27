from __future__ import annotations

import unittest

from sshcnfgr.enrich import (
    DnsEnrichResult,
    apply_dns_enrichment,
    build_alias_base,
    bulk_generate_aliases,
    enrich_hosts_dns,
    resolve_fqdn_and_ip,
    suggest_host_alias,
)
from sshcnfgr.model import HostDatabase, HostEntry, HostGroup


class DnsEnrichmentTests(unittest.TestCase):
    def test_short_hostname_expands_to_fqdn_and_prefers_ipv4(self) -> None:
        def fake_canon(name: str) -> tuple[str | None, list[str]]:
            if name == "sdvdmg-mongodb":
                return (
                    "sdvdmg-mongodb.slub-dresden.de",
                    ["2001:db8::42", "10.20.30.40"],
                )
            return None, []

        fqdn, ip_addr = resolve_fqdn_and_ip(
            "sdvdmg-mongodb",
            canon_resolver=fake_canon,
            reverse_resolver=lambda _ip: None,
        )
        self.assertEqual(fqdn, "sdvdmg-mongodb.slub-dresden.de")
        self.assertEqual(ip_addr, "10.20.30.40")

    def test_bare_ip_uses_fcrdns_and_rejects_unconfirmed_ptr(self) -> None:
        def fake_canon(name: str) -> tuple[str | None, list[str]]:
            if name == "db01.slub-dresden.de":
                return ("db01.slub-dresden.de", ["10.0.0.12"])
            if name == "other.slub-dresden.de":
                return ("other.slub-dresden.de", ["10.0.0.99"])
            return None, []

        def fake_rev(ip: str) -> str | None:
            return {
                "10.0.0.12": "db01.slub-dresden.de",
                "10.0.0.13": "other.slub-dresden.de",
            }.get(ip)

        fqdn_ok, ip_ok = resolve_fqdn_and_ip(
            "10.0.0.12",
            canon_resolver=fake_canon,
            reverse_resolver=fake_rev,
        )
        self.assertEqual(fqdn_ok, "db01.slub-dresden.de")
        self.assertEqual(ip_ok, "10.0.0.12")

        # PTR loest nicht wieder auf 10.0.0.13 auf -> FQDN ablehnen, IP behalten.
        fqdn_bad, ip_bad = resolve_fqdn_and_ip(
            "10.0.0.13",
            canon_resolver=fake_canon,
            reverse_resolver=fake_rev,
        )
        self.assertIsNone(fqdn_bad)
        self.assertEqual(ip_bad, "10.0.0.13")

    def test_existing_fqdn_cname_is_preserved_and_only_ip_filled(self) -> None:
        def fake_canon(name: str) -> tuple[str | None, list[str]]:
            if name == "gitlab.slub-dresden.de":
                return ("git-backend-03.intern.slub-dresden.de", ["10.1.2.3"])
            return None, []

        fqdn, ip_addr = resolve_fqdn_and_ip(
            "gitlab.slub-dresden.de",
            canon_resolver=fake_canon,
            reverse_resolver=lambda _ip: None,
        )
        self.assertIsNone(fqdn)
        self.assertEqual(ip_addr, "10.1.2.3")

    def test_enrich_hosts_and_apply_transactional(self) -> None:
        db = HostDatabase(
            hosts=[
                HostEntry(id="h1", name="mongo", host_name="sdvdmg-mongodb"),
                HostEntry(id="h2", name="ip-box", host_name="10.0.0.12"),
                HostEntry(id="h3", name="offline", host_name="nope.invalid"),
            ]
        )

        def fake_canon(name: str) -> tuple[str | None, list[str]]:
            mapping = {
                "sdvdmg-mongodb": ("sdvdmg-mongodb.slub-dresden.de", ["10.20.30.40"]),
                "db01.slub-dresden.de": ("db01.slub-dresden.de", ["10.0.0.12"]),
            }
            return mapping.get(name, (None, []))

        def fake_rev(ip: str) -> str | None:
            return "db01.slub-dresden.de" if ip == "10.0.0.12" else None

        results = enrich_hosts_dns(
            db.hosts,
            canon_resolver=fake_canon,
            reverse_resolver=fake_rev,
        )
        self.assertEqual(
            results["h1"],
            DnsEnrichResult(host_id="h1", fqdn="sdvdmg-mongodb.slub-dresden.de", ip="10.20.30.40"),
        )
        self.assertEqual(
            results["h2"],
            DnsEnrichResult(host_id="h2", fqdn="db01.slub-dresden.de", ip="10.0.0.12"),
        )
        self.assertFalse(results["h3"].resolved)

        updated_db, updated, unresolved, errors = apply_dns_enrichment(
            db,
            {"h1", "h2", "h3"},
            results,
        )
        self.assertEqual(errors, [])
        self.assertEqual((updated, unresolved), (2, 1))
        # Original-DB unveraendert (transaktional).
        self.assertEqual(db.get_by_id("h1").host_name, "sdvdmg-mongodb")  # type: ignore[union-attr]
        self.assertEqual(
            updated_db.get_by_id("h1").host_name,  # type: ignore[union-attr]
            "sdvdmg-mongodb.slub-dresden.de",
        )
        self.assertEqual(updated_db.get_by_id("h1").ip, "10.20.30.40")  # type: ignore[union-attr]
        self.assertEqual(
            updated_db.get_by_id("h2").host_name,  # type: ignore[union-attr]
            "db01.slub-dresden.de",
        )
        self.assertEqual(updated_db.get_by_id("h2").ip, "10.0.0.12")  # type: ignore[union-attr]


class AliasGeneratorTests(unittest.TestCase):
    def test_build_alias_base_uses_direct_group_global_and_ip(self) -> None:
        db = HostDatabase(
            groups=[HostGroup(name="prod", user="ops")],
            global_options={"User": "fallback"},
            hosts=[
                HostEntry(
                    id="h1",
                    name="old1",
                    host_name="sdvdmg-mongodb.slub-dresden.de",
                    user="baer",
                ),
                HostEntry(
                    id="h2",
                    name="old2",
                    host_name="app01.slub-dresden.de",
                    groups=["prod"],
                ),
                HostEntry(id="h3", name="old3", host_name="10.0.0.12"),
            ],
        )
        self.assertEqual(build_alias_base(db.hosts[0], db), "baer@sdvdmg-mongodb")
        self.assertEqual(build_alias_base(db.hosts[1], db), "ops@app01")
        self.assertEqual(build_alias_base(db.hosts[2], db), "fallback@10.0.0.12")

        no_user_db = HostDatabase(
            hosts=[HostEntry(id="h4", name="old4", host_name="Web01.Example.ORG")]
        )
        self.assertEqual(build_alias_base(no_user_db.hosts[0], no_user_db), "web01")

    def test_suggest_and_bulk_generate_aliases_resolve_collisions(self) -> None:
        db = HostDatabase(
            hosts=[
                HostEntry(
                    id="h1",
                    name="srv-a",
                    host_name="app.dev.example.org",
                    user="baer",
                ),
                HostEntry(
                    id="h2",
                    name="srv-b",
                    host_name="app.prod.example.org",
                    user="baer",
                ),
                HostEntry(
                    id="h3",
                    name="srv-c",
                    host_name="app.stage.example.org",
                    user="baer",
                ),
            ]
        )

        # Einzelvorschlag fuer h1 ohne Kollision.
        self.assertEqual(suggest_host_alias(db.hosts[0], db), "baer@app")

        updated_db, renames, errors = bulk_generate_aliases(db, {"h1", "h2", "h3"})
        self.assertEqual(errors, [])
        self.assertEqual(
            renames,
            [
                ("srv-a", "baer@app"),
                ("srv-b", "baer@app-2"),
                ("srv-c", "baer@app-3"),
            ],
        )
        self.assertEqual(
            [h.name for h in updated_db.hosts],
            ["baer@app", "baer@app-2", "baer@app-3"],
        )
        # Original-DB unveraendert.
        self.assertEqual([h.name for h in db.hosts], ["srv-a", "srv-b", "srv-c"])


if __name__ == "__main__":
    unittest.main()
