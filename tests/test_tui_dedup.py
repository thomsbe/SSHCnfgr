from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import DataTable, Input, Select

from sshcnfgr.model import HostDatabase, HostEntry, HostGroup, IdentityProfile
from sshcnfgr.settings import load_ui_theme_name, save_ui_theme_name
from sshcnfgr.store import load_database, save_database
from sshcnfgr.tui import SSHCnfgrApp


class TuiDedupTests(unittest.IsolatedAsyncioTestCase):
    async def test_dedup_screen_opens_merges_and_updates_main_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "hosts.toml"
            settings_path = tmp / "app.toml"

            initial_db = HostDatabase(
                groups=[HostGroup(name="prod")],
                identities=[
                    IdentityProfile(name="id_a", identity_file="~/.ssh/id_a"),
                    IdentityProfile(name="id_b", identity_file="~/.ssh/id_b"),
                ],
                hosts=[
                    HostEntry(
                        id="h1",
                        name="web-main",
                        enabled=True,
                        host_name="10.0.0.10",
                        user="ubuntu",
                        port=22,
                        identity="id_a",
                        groups=["prod"],
                        extra_options={"ForwardAgent": "yes"},
                    ),
                    HostEntry(
                        id="h2",
                        name="web-copy",
                        enabled=True,
                        host_name="10.0.0.10",
                        user="ubuntu",
                        port=22,
                        identity="id_b",
                        extra_options={"ForwardAgent": "no", "ProxyJump": "bastion"},
                    ),
                    HostEntry(
                        id="h3",
                        name="db-only",
                        enabled=True,
                        host_name="10.0.0.20",
                        user="postgres",
                        port=5432,
                    ),
                ],
            )
            save_database(initial_db, db_path, backup=False)

            def _load_db() -> HostDatabase:
                return load_database(db_path)

            def _save_db(db: HostDatabase) -> None:
                save_database(db, db_path)

            def _load_theme() -> str:
                return load_ui_theme_name(settings_path)

            def _save_theme(theme_name: str) -> None:
                save_ui_theme_name(theme_name, settings_path)

            with (
                patch("sshcnfgr.tui.load_database", side_effect=_load_db),
                patch("sshcnfgr.tui.save_database", side_effect=_save_db),
                patch("sshcnfgr.dedup_screen.save_database", side_effect=_save_db),
                patch("sshcnfgr.tui.load_ui_theme_name", side_effect=_load_theme),
                patch("sshcnfgr.tui.save_ui_theme_name", side_effect=_save_theme),
            ):
                app = SSHCnfgrApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause()

                    # Theme-Toggle mit Textual-8 self.theme pruefen.
                    initial_theme = app.theme
                    await pilot.press("ctrl+t")
                    await pilot.pause()
                    self.assertNotEqual(app.theme, initial_theme)

                    # Dubletten-Screen oeffnen.
                    await pilot.press("ctrl+u")
                    await pilot.pause()

                    screen = app.screen
                    groups_table = screen.query_one("#dedup_groups_table", DataTable)
                    self.assertEqual(groups_table.row_count, 1)

                    members_table = screen.query_one("#dedup_members_table", DataTable)
                    self.assertEqual(members_table.row_count, 2)

                    # Standardmaessig wird der erste alphabetische Host (web-copy) vorausgewaehlt;
                    # auf web-main umschalten und Merge ausfuehren.
                    primary_select = screen.query_one("#dedup_primary_select", Select)
                    primary_select.value = "h1"
                    await pilot.pause()

                    target_input = screen.query_one("#dedup_target_name", Input)
                    self.assertEqual(target_input.value, "web-main")

                    await pilot.press("ctrl+m")
                    await pilot.pause()

                    # Nach dem Merge mit "disable" ist die Gruppe aufgeloest.
                    self.assertEqual(groups_table.row_count, 0)

                    # Zurueck zur Hauptansicht.
                    await pilot.press("escape")
                    await pilot.pause()

                    reloaded = load_database(db_path)
                    main_host = reloaded.get_by_id("h1")
                    copy_host = reloaded.get_by_id("h2")
                    self.assertIsNotNone(main_host)
                    self.assertIsNotNone(copy_host)
                    assert main_host is not None and copy_host is not None
                    self.assertTrue(main_host.enabled)
                    self.assertFalse(copy_host.enabled)
                    self.assertEqual(main_host.extra_options.get("ProxyJump"), "bastion")

                    # Zeitstempel-Backup wurde vor dem Speichern angelegt.
                    backups = list(tmp.glob("hosts.toml.bak.*"))
                    self.assertGreaterEqual(len(backups), 1)

    async def test_dedup_screen_dns_check_finds_name_vs_ip(self) -> None:
        from sshcnfgr.dedup import resolve_hostnames_dns

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "sshcnfgr.toml"
            settings_path = tmp / "app.toml"

            initial_db = HostDatabase(
                hosts=[
                    HostEntry(id="h1", name="srv-ip", host_name="10.0.0.44", user="admin"),
                    HostEntry(id="h2", name="srv-name", host_name="srv01.intern", user="admin"),
                ]
            )
            save_database(initial_db, db_path, backup=False)

            def _fake_dns(hosts: list[HostEntry]) -> object:
                return resolve_hostnames_dns(
                    hosts,
                    forward_resolver=lambda name: (
                        {"10.0.0.44"} if name == "srv01.intern" else set()
                    ),
                    reverse_resolver=lambda _ip: None,
                )

            with (
                patch("sshcnfgr.tui.load_database", side_effect=lambda: load_database(db_path)),
                patch(
                    "sshcnfgr.tui.save_database",
                    side_effect=lambda d: save_database(d, db_path),
                ),
                patch(
                    "sshcnfgr.dedup_screen.save_database",
                    side_effect=lambda d: save_database(d, db_path),
                ),
                patch("sshcnfgr.dedup_screen.resolve_hostnames_dns", side_effect=_fake_dns),
                patch(
                    "sshcnfgr.tui.load_ui_theme_name",
                    side_effect=lambda: load_ui_theme_name(settings_path),
                ),
                patch(
                    "sshcnfgr.tui.save_ui_theme_name",
                    side_effect=lambda t: save_ui_theme_name(t, settings_path),
                ),
            ):
                app = SSHCnfgrApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause()
                    await pilot.press("ctrl+u")
                    await pilot.pause()

                    groups_table = app.screen.query_one("#dedup_groups_table", DataTable)
                    self.assertEqual(groups_table.row_count, 0)

                    # Expliziten DNS-Check per Ctrl+R ausloesen.
                    await pilot.press("ctrl+r")
                    await pilot.pause()
                    self.assertEqual(groups_table.row_count, 1)


if __name__ == "__main__":
    unittest.main()
