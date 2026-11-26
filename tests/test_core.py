from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path

from sshcnfgr.identities import merge_discovered_identities
from sshcnfgr.model import HostDatabase, HostEntry, IdentityProfile

HAS_LOGURU = importlib.util.find_spec("loguru") is not None
HAS_TOMLI_W = importlib.util.find_spec("tomli_w") is not None


class ModelAndIdentitiesTests(unittest.TestCase):
    def test_case_insensitive_resolvers(self) -> None:
        db = HostDatabase(
            global_options={
                "identityfile": "~/.ssh/id_global",
                "identityagent": "/tmp/agent.sock",
                "port": "2200",
                "user": "deploy",
            },
            hosts=[HostEntry(id="h1", name="app", host_name="10.0.0.5")],
        )
        host = db.hosts[0]
        self.assertEqual(db.resolve_identity_file(host), "~/.ssh/id_global")
        self.assertEqual(db.resolve_identity_agent(host), "/tmp/agent.sock")
        self.assertEqual(db.resolve_port(host), 2200)
        self.assertEqual(db.resolve_user(host), "deploy")

    def test_merge_discovered_identities_preserves_disabled_flag(self) -> None:
        db = HostDatabase(
            identities=[
                IdentityProfile(
                    name="id_ed25519",
                    identity_file="/home/user/.ssh/id_ed25519",
                    enabled=False,
                )
            ]
        )
        discovered = [
            IdentityProfile(
                name="id_ed25519",
                identity_file="/home/user/.ssh/id_ed25519",
                source="local-ssh",
                public_key_file="/home/user/.ssh/id_ed25519.pub",
                public_key_preview="ssh-ed25519 user@host",
                enabled=True,
            )
        ]

        created, updated = merge_discovered_identities(db, discovered)
        self.assertEqual((created, updated), (0, 1))
        self.assertFalse(db.identities[0].enabled)


@unittest.skipUnless(HAS_LOGURU, "loguru nicht im aktuellen Python-Environment installiert")
class ImporterTests(unittest.TestCase):
    def test_import_handles_match_blocks_and_equals_syntax(self) -> None:
        from sshcnfgr.importer import import_ssh_config

        sample = "\n".join(
            [
                "Include ~/.ssh/config.d/*",
                "ServerAliveInterval=30",
                "",
                "Host app",
                "  HostName=10.1.2.3",
                "  User=alice",
                "  Port=2222",
                "",
                "Match host *.internal",
                "  User bob",
                "  Port 9999",
                "",
                "Host *",
                "  IdentityFile ~/.ssh/id_default",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg = Path(tmp_dir) / "config"
            cfg.write_text(sample, encoding="utf-8")
            db, report = import_ssh_config(cfg)

        self.assertEqual(len(db.hosts), 1)
        app = db.hosts[0]
        self.assertEqual(app.name, "app")
        self.assertEqual(app.host_name, "10.1.2.3")
        # Match-Direktiven duerfen nicht in 'app' leaken.
        self.assertEqual(app.user, "alice")
        self.assertEqual(app.port, 2222)
        self.assertNotIn("Match", app.extra_options)
        self.assertEqual(db.global_options.get("Include"), "~/.ssh/config.d/*")
        self.assertEqual(db.global_options.get("ServerAliveInterval"), "30")
        self.assertEqual(db.global_options.get("IdentityFile"), "~/.ssh/id_default")
        self.assertTrue(any("Match-Block" in w for w in report.warnings))


@unittest.skipUnless(HAS_TOMLI_W, "tomli_w nicht im aktuellen Python-Environment installiert")
class GeneratorAndStoreTests(unittest.TestCase):
    def test_generator_places_include_first_and_host_wildcard_last(self) -> None:
        from sshcnfgr.generator import generate_config, write_generated_config

        db = HostDatabase(
            global_options={
                "Include": "~/.ssh/config.d/*",
                "IdentityFile": "~/.ssh/id_default",
                "ServerAliveInterval": "60",
            },
            hosts=[
                HostEntry(
                    id="h1",
                    name="alpha",
                    host_name="10.0.0.1",
                    user="admin",
                    identity_file="~/.ssh/id_default",
                ),
                HostEntry(
                    id="h2",
                    name="disabled-host",
                    enabled=False,
                    host_name="10.0.0.2",
                ),
            ],
        )

        rendered = generate_config(db, include_timestamp=False)
        include_pos = rendered.index("Include ~/.ssh/config.d/*")
        alpha_pos = rendered.index("Host alpha")
        wildcard_pos = rendered.index("Host *")

        self.assertLess(include_pos, alpha_pos)
        self.assertLess(alpha_pos, wildcard_pos)
        self.assertNotIn("disabled-host", rendered)
        # Global IdentityFile wird nicht redundant im Host-Block wiederholt.
        alpha_section = rendered[alpha_pos:wildcard_pos]
        self.assertNotIn("IdentityFile", alpha_section)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "config.generated"
            out.write_text("old content", encoding="utf-8")
            write_generated_config(db, output=out)

            if os.name == "posix":
                mode = stat.S_IMODE(out.stat().st_mode)
                self.assertEqual(mode, 0o600)
            backups = list(Path(tmp_dir).glob("config.generated.bak.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "old content")

    def test_store_save_creates_backup_and_roundtrips(self) -> None:
        from sshcnfgr.settings import load_ui_theme_name, save_ui_theme_name
        from sshcnfgr.store import load_database, save_database

        db = HostDatabase(
            hosts=[
                HostEntry(id="b", name="zeta", host_name="10.0.0.9"),
                HostEntry(id="a", name="alpha", host_name="10.0.0.1"),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "sshcnfgr.toml"
            save_database(db, db_path)
            save_ui_theme_name("textual-light", db_path)
            save_database(db, db_path)

            if os.name == "posix":
                mode = stat.S_IMODE(db_path.stat().st_mode)
                self.assertEqual(mode, 0o600)

            backups = list(Path(tmp_dir).glob("sshcnfgr.toml.bak.*"))
            self.assertEqual(len(backups), 1)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)

            reloaded = load_database(db_path)
            self.assertEqual([h.name for h in reloaded.hosts], ["alpha", "zeta"])
            # Theme bleibt beim erneuten save_database erhalten (Single-File-Design).
            self.assertEqual(load_ui_theme_name(db_path), "textual-light")

    def test_store_falls_back_to_legacy_hosts_toml_when_default_missing(self) -> None:
        from unittest.mock import patch

        from sshcnfgr.store import load_database, save_database

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            new_path = tmp / ".ssh" / "sshcnfgr.toml"
            legacy_path = tmp / ".config" / "sshcnfgr" / "hosts.toml"
            legacy_db = HostDatabase(
                hosts=[HostEntry(id="l1", name="legacy-host", host_name="10.0.0.42")]
            )
            save_database(legacy_db, legacy_path, backup=False)

            with (
                patch("sshcnfgr.store.DB_PATH", new_path),
                patch("sshcnfgr.store.LEGACY_DB_PATH", legacy_path),
            ):
                loaded = load_database()
                self.assertEqual([h.name for h in loaded.hosts], ["legacy-host"])


if __name__ == "__main__":
    unittest.main()
