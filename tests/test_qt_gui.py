from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sshcnfgr.model import HostDatabase, HostEntry, HostGroup, IdentityProfile
from sshcnfgr.store import load_database, save_database

HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None


@unittest.skipUnless(HAS_PYSIDE6, "PySide6-Essentials nicht installiert")
class QtGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def _sample_db(self) -> HostDatabase:
        return HostDatabase(
            groups=[HostGroup(name="prod", description="Produktion", identity="id_a")],
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
                    port=2222,
                    identity="id_a",
                    groups=["prod"],
                    tags=["web"],
                    extra_options={"ForwardAgent": "yes"},
                ),
                HostEntry(
                    id="h2",
                    name="web-copy",
                    enabled=True,
                    host_name="10.0.0.10",
                    user="ubuntu",
                    port=2222,
                    identity="id_b",
                    extra_options={"ForwardAgent": "no", "ProxyJump": "bastion"},
                ),
                HostEntry(
                    id="h3",
                    name="db-off",
                    enabled=False,
                    host_name="10.0.0.20",
                    user="postgres",
                    port=5432,
                ),
            ],
        )

    def test_main_window_filter_edit_and_save_host(self) -> None:
        from PySide6.QtWidgets import QTableWidgetItem

        from sshcnfgr.gui.main_window import SSHCnfgrWindow

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "hosts.toml"
            save_database(self._sample_db(), db_path, backup=False)

            def _save(db: HostDatabase) -> None:
                save_database(db, db_path)

            with patch("sshcnfgr.gui.main_window.save_database", side_effect=_save):
                window = SSHCnfgrWindow(db=load_database(db_path))
                try:
                    self.assertEqual(window.hosts_table.rowCount(), 3)
                    self.assertIn("Dubletten (1)", window.btn_host_dedup.text())

                    # Suche & "Nur aktive" testen.
                    window.host_only_active_cb.setChecked(True)
                    self.assertEqual(window.hosts_table.rowCount(), 2)
                    window.host_search_input.setText("web-main")
                    self.assertEqual(window.hosts_table.rowCount(), 1)

                    # Host auswaehlen, Port leeren & Extra-Option hinzufuegen.
                    window.hosts_table.selectRow(0)
                    self.assertEqual(window.selected_host_id, "h1")
                    window.in_host_port.clear()
                    row = window.extra_options_table.rowCount()
                    window.extra_options_table.insertRow(row)
                    window.extra_options_table.setItem(row, 0, QTableWidgetItem("Compression"))
                    window.extra_options_table.setItem(row, 1, QTableWidgetItem("yes"))

                    window.action_save_host()

                    reloaded = load_database(db_path)
                    updated = reloaded.get_by_id("h1")
                    self.assertIsNotNone(updated)
                    assert updated is not None
                    self.assertIsNone(updated.port)
                    self.assertEqual(updated.extra_options.get("Compression"), "yes")

                    # Config-Vorschau pruefen.
                    window._refresh_preview()
                    preview_text = window.preview_edit.toPlainText()
                    self.assertIn("Host web-main", preview_text)
                    self.assertNotIn("Host db-off", preview_text)
                finally:
                    window.close()

    def test_dedup_dialog_merges_group_and_saves_backup(self) -> None:
        from sshcnfgr.gui.dedup_dialog import DuplicateReviewDialog

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "hosts.toml"
            save_database(self._sample_db(), db_path, backup=False)

            def _save(db: HostDatabase) -> None:
                save_database(db, db_path)

            with patch("sshcnfgr.gui.dedup_dialog.save_database", side_effect=_save):
                dialog = DuplicateReviewDialog(load_database(db_path))
                try:
                    self.assertEqual(dialog.groups_table.rowCount(), 1)
                    self.assertEqual(dialog.members_table.rowCount(), 2)
                    self.assertIn("identity", dialog._conflict_combos)
                    self.assertIn("extra:ForwardAgent", dialog._conflict_combos)

                    # Primary auf web-main (h1) stellen und zusammenfuehren.
                    idx = dialog.primary_combo.findData("h1")
                    self.assertGreaterEqual(idx, 0)
                    dialog.primary_combo.setCurrentIndex(idx)
                    self.assertEqual(dialog.target_name_input.text(), "web-main")

                    dialog.action_merge_current()

                    self.assertTrue(dialog.changed)
                    self.assertEqual(dialog.groups_table.rowCount(), 0)

                    reloaded = load_database(db_path)
                    main_host = reloaded.get_by_id("h1")
                    copy_host = reloaded.get_by_id("h2")
                    assert main_host is not None and copy_host is not None
                    self.assertTrue(main_host.enabled)
                    self.assertFalse(copy_host.enabled)
                    self.assertEqual(main_host.extra_options.get("ProxyJump"), "bastion")
                    self.assertGreaterEqual(len(list(tmp.glob("hosts.toml.bak.*"))), 1)
                finally:
                    dialog.close()

    def test_group_drag_drop_reordering_and_match_defaults(self) -> None:
        from PySide6.QtWidgets import QTableWidgetItem

        from sshcnfgr.gui.main_window import SSHCnfgrWindow

        db = HostDatabase(
            groups=[
                HostGroup(name="lab", description="Test"),
                HostGroup(name="prod", description="Wichtig", identity="id_a"),
            ],
            identities=[IdentityProfile(name="id_a", identity_file="~/.ssh/id_a")],
            hosts=[
                HostEntry(id="h1", name="a-lab", host_name="192.168.1.10", groups=["lab"]),
                HostEntry(id="h2", name="z-prod", host_name="10.0.0.10", groups=["prod"]),
            ],
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "sshcnfgr.toml"
            save_database(db, db_path, backup=False)

            def _save(updated_db: HostDatabase) -> None:
                save_database(updated_db, db_path)

            with patch("sshcnfgr.gui.main_window.save_database", side_effect=_save):
                window = SSHCnfgrWindow(db=load_database(db_path))
                try:
                    # Ausgangslage: lab vor prod
                    self.assertEqual(window.hosts_table.item(0, 0).text(), "a-lab")  # type: ignore[union-attr]

                    # Drag & Drop simulieren: prod (Zeile 1) auf Position 0 verschieben.
                    window.groups_table.row_moved.emit(1, 0)
                    self.assertEqual([g.name for g in window.db.groups], ["prod", "lab"])
                    self.assertEqual(window.hosts_table.item(0, 0).text(), "z-prod")  # type: ignore[union-attr]

                    # Gruppen-Defaults (User, Port, Extra-Option) fuer prod speichern.
                    window.groups_table.selectRow(0)
                    window.in_group_user.setText("ubuntu")
                    window.in_group_port.setText("2222")
                    row = window.group_extra_options_table.rowCount()
                    window.group_extra_options_table.insertRow(row)
                    window.group_extra_options_table.setItem(
                        row, 0, QTableWidgetItem("IdentitiesOnly")
                    )
                    window.group_extra_options_table.setItem(row, 1, QTableWidgetItem("yes"))
                    window.action_save_group()

                    preview = window.preview_edit.toPlainText()
                    self.assertLess(preview.index("Host z-prod"), preview.index("Host a-lab"))
                    self.assertIn("Match originalhost z-prod", preview)
                    self.assertIn("IdentitiesOnly yes", preview)

                    reloaded = load_database(db_path)
                    self.assertEqual([g.name for g in reloaded.groups], ["prod", "lab"])
                    self.assertEqual(reloaded.groups[0].user, "ubuntu")
                    self.assertEqual(reloaded.groups[0].port, 2222)
                finally:
                    window.close()

    def test_multi_select_bulk_actions(self) -> None:
        from PySide6.QtCore import QItemSelectionModel

        from sshcnfgr.gui.main_window import SSHCnfgrWindow

        db = HostDatabase(
            groups=[HostGroup(name="prod"), HostGroup(name="lab")],
            hosts=[
                HostEntry(id="h1", name="srv-1", host_name="10.0.0.1", enabled=True),
                HostEntry(id="h2", name="srv-2", host_name="10.0.0.2", enabled=True),
                HostEntry(id="h3", name="srv-3", host_name="10.0.0.3", enabled=True),
            ],
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "sshcnfgr.toml"
            save_database(db, db_path, backup=False)

            def _save(updated_db: HostDatabase) -> None:
                save_database(updated_db, db_path)

            with patch("sshcnfgr.gui.main_window.save_database", side_effect=_save):
                window = SSHCnfgrWindow(db=load_database(db_path))
                try:
                    # Zwei Zeilen (srv-1 und srv-2) gleichzeitig markieren.
                    sel_model = window.hosts_table.selectionModel()
                    flags = (
                        QItemSelectionModel.SelectionFlag.Select
                        | QItemSelectionModel.SelectionFlag.Rows
                    )
                    sel_model.select(window.hosts_table.model().index(0, 0), flags)
                    sel_model.select(window.hosts_table.model().index(1, 0), flags)

                    self.assertEqual(len(window.selected_host_ids()), 2)
                    self.assertIn("2 Hosts markiert", window.lbl_bulk_selection.text())
                    self.assertFalse(window.btn_host_save.isEnabled())

                    # Beide markierten Hosts als 1. Gruppe 'prod' zuweisen.
                    idx = window.bulk_group_combo.findData("prod")
                    window.bulk_group_combo.setCurrentIndex(idx)
                    window.action_bulk_add_group(as_primary=True)

                    reloaded = load_database(db_path)
                    self.assertEqual(reloaded.get_by_id("h1").groups, ["prod"])  # type: ignore[union-attr]
                    self.assertEqual(reloaded.get_by_id("h2").groups, ["prod"])  # type: ignore[union-attr]
                    self.assertEqual(reloaded.get_by_id("h3").groups, [])  # type: ignore[union-attr]

                    # Beide deaktivieren, dann wieder aktivieren.
                    window.action_bulk_set_enabled(False)
                    reloaded = load_database(db_path)
                    self.assertFalse(reloaded.get_by_id("h1").enabled)  # type: ignore[union-attr]
                    self.assertFalse(reloaded.get_by_id("h2").enabled)  # type: ignore[union-attr]
                    self.assertTrue(reloaded.get_by_id("h3").enabled)  # type: ignore[union-attr]

                    window.action_bulk_set_enabled(True)
                    reloaded = load_database(db_path)
                    self.assertTrue(reloaded.get_by_id("h1").enabled)  # type: ignore[union-attr]
                    self.assertTrue(reloaded.get_by_id("h2").enabled)  # type: ignore[union-attr]

                    # Gruppe wieder per Sammel-Aktion entfernen.
                    window.action_bulk_remove_group()
                    reloaded = load_database(db_path)
                    self.assertEqual(reloaded.get_by_id("h1").groups, [])  # type: ignore[union-attr]
                    self.assertEqual(reloaded.get_by_id("h2").groups, [])  # type: ignore[union-attr]
                finally:
                    window.close()


if __name__ == "__main__":
    unittest.main()
