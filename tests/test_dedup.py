from __future__ import annotations

import unittest

from sshcnfgr.dedup import (
    MergePlan,
    analyze_group_conflicts,
    apply_merge,
    build_merged_host,
    default_conflict_choices,
    find_duplicate_groups,
)
from sshcnfgr.model import HostDatabase, HostEntry, HostGroup, IdentityProfile


class DedupTests(unittest.TestCase):
    def _sample_db(self) -> HostDatabase:
        return HostDatabase(
            groups=[
                HostGroup(name="prod"),
                HostGroup(name="legacy"),
            ],
            identities=[
                IdentityProfile(name="id_prod", identity_file="~/.ssh/id_ed25519"),
                IdentityProfile(name="id_old", identity_file="~/.ssh/id_rsa"),
            ],
            global_options={"Port": "22", "User": "ubuntu"},
            hosts=[
                HostEntry(
                    id="h1",
                    name="web-prod",
                    enabled=True,
                    host_name="10.0.0.12",
                    user="ubuntu",
                    port=22,
                    identity="id_prod",
                    groups=["prod"],
                    tags=["k8s"],
                    extra_options={"ForwardAgent": "yes", "ServerAliveInterval": "30"},
                ),
                HostEntry(
                    id="h2",
                    name="web-prod-1",
                    enabled=True,
                    host_name="10.0.0.12",
                    user=None,  # erbt global "ubuntu"
                    port=None,  # erbt global 22
                    identity="id_old",
                    groups=["legacy"],
                    tags=["web", "k8s"],
                    extra_options={
                        "forwardagent": "no",
                        "ProxyJump": "bastion",
                    },
                ),
                HostEntry(
                    id="h3",
                    name="web-root",
                    enabled=True,
                    host_name="10.0.0.12",
                    user="root",
                    port=22,
                ),
                HostEntry(
                    id="h4",
                    name="web-disabled",
                    enabled=False,
                    host_name="10.0.0.12",
                    user="ubuntu",
                    port=22,
                ),
            ],
        )

    def test_find_duplicate_groups_matches_effective_target_and_filters_inactive(self) -> None:
        db = self._sample_db()

        active_groups = find_duplicate_groups(db, include_inactive=False)
        self.assertEqual(len(active_groups), 1)
        group = active_groups[0]
        self.assertEqual(group.label, "ubuntu@10.0.0.12:22")
        self.assertEqual(group.aliases, ["web-prod", "web-prod-1"])

        all_groups = find_duplicate_groups(db, include_inactive=True)
        self.assertEqual(len(all_groups), 1)
        self.assertEqual(all_groups[0].aliases, ["web-disabled", "web-prod", "web-prod-1"])

    def test_find_duplicate_groups_normalizes_hostname_case(self) -> None:
        db = HostDatabase(
            hosts=[
                HostEntry(
                    id="a",
                    name="srv-a",
                    host_name="App.Example.COM",
                    user="admin",
                    port=2222,
                ),
                HostEntry(
                    id="b",
                    name="srv-b",
                    host_name="app.example.com",
                    user="admin",
                    port=2222,
                ),
            ]
        )

        groups = find_duplicate_groups(db)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].aliases, ["srv-a", "srv-b"])

        conflicts = analyze_group_conflicts(groups[0])
        self.assertEqual([c.field for c in conflicts], ["host_name"])

    def test_analyze_group_conflicts_detects_identity_and_case_insensitive_extra(self) -> None:
        db = self._sample_db()
        group = find_duplicate_groups(db)[0]

        conflicts = analyze_group_conflicts(group)
        fields = [c.field for c in conflicts]
        self.assertEqual(fields, ["identity", "extra:ForwardAgent"])

        defaults = default_conflict_choices(group, "h1", conflicts)
        self.assertEqual(defaults["identity"], "id_prod")
        self.assertEqual(defaults["extra:ForwardAgent"], "yes")

    def test_build_merged_host_combines_non_conflicting_fields_and_unions_lists(self) -> None:
        db = self._sample_db()
        group = find_duplicate_groups(db)[0]

        merged = build_merged_host(
            group=group,
            primary_host_id="h1",
            target_name="web-prod",
            resolved_fields={"identity": "id_prod", "extra:ForwardAgent": "no"},
        )

        self.assertEqual(merged.id, "h1")
        self.assertEqual(merged.name, "web-prod")
        self.assertEqual(merged.user, "ubuntu")
        self.assertEqual(merged.port, 22)
        self.assertEqual(merged.identity, "id_prod")
        self.assertEqual(merged.groups, ["prod", "legacy"])
        self.assertEqual(merged.tags, ["k8s", "web"])
        self.assertEqual(
            merged.extra_options,
            {
                "ForwardAgent": "no",
                "ProxyJump": "bastion",
                "ServerAliveInterval": "30",
            },
        )

    def test_apply_merge_disable_resolves_duplicate_without_deleting(self) -> None:
        db = self._sample_db()
        group = find_duplicate_groups(db)[0]
        plan = MergePlan(
            group=group,
            primary_host_id="h1",
            target_name="web-prod",
            resolved_fields={"identity": "id_prod", "extra:ForwardAgent": "yes"},
            disposition="disable",
        )

        updated_db, merged, errors = apply_merge(db, plan)
        self.assertEqual(errors, [])
        self.assertEqual(merged.name, "web-prod")

        # Original DB bleibt unveraendert (transaktional).
        self.assertTrue(db.get_by_id("h2").enabled)  # type: ignore[union-attr]

        # In neuer DB ist Dublette deaktiviert und Gruppe bei aktiven Hosts aufgeloest.
        disabled = updated_db.get_by_id("h2")
        self.assertIsNotNone(disabled)
        self.assertFalse(disabled.enabled)  # type: ignore[union-attr]
        self.assertEqual(find_duplicate_groups(updated_db, include_inactive=False), [])

    def test_apply_merge_delete_removes_duplicates_and_allows_alias_reuse(self) -> None:
        db = self._sample_db()
        group = find_duplicate_groups(db)[0]
        plan = MergePlan(
            group=group,
            primary_host_id="h1",
            target_name="web-prod-1",
            resolved_fields={"identity": "id_old", "extra:ForwardAgent": None},
            disposition="delete",
        )

        updated_db, merged, errors = apply_merge(db, plan)
        self.assertEqual(errors, [])
        self.assertEqual(merged.name, "web-prod-1")
        self.assertNotIn("ForwardAgent", merged.extra_options)
        self.assertIsNone(updated_db.get_by_id("h2"))

    def test_apply_merge_rejects_alias_collision_when_disabling(self) -> None:
        db = self._sample_db()
        group = find_duplicate_groups(db)[0]
        plan = MergePlan(
            group=group,
            primary_host_id="h1",
            target_name="web-prod-1",  # kollidiert mit deaktiviertem h2
            resolved_fields={"identity": "id_prod", "extra:ForwardAgent": "yes"},
            disposition="disable",
        )

        _, _, errors = apply_merge(db, plan)
        self.assertTrue(any("doppelt vorhanden" in err for err in errors))


if __name__ == "__main__":
    unittest.main()
