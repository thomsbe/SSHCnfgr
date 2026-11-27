from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QPoint, Qt, QThread, Signal
from PySide6.QtGui import QAction, QCloseEvent, QColor, QDropEvent, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..dedup import find_duplicate_groups
from ..enrich import (
    DnsEnrichResult,
    apply_dns_enrichment,
    bulk_generate_aliases,
    enrich_hosts_dns,
    resolve_fqdn_and_ip,
    suggest_host_alias,
)
from ..generator import generate_config, write_generated_config
from ..identities import discover_ssh_identities, merge_discovered_identities
from ..importer import import_ssh_config
from ..model import HostDatabase, HostEntry, HostGroup, IdentityProfile
from ..paths import GENERATED_CONFIG_PATH
from ..store import load_database, save_database
from .dedup_dialog import DuplicateReviewDialog

MUTED_COLOR = QColor(135, 135, 135)


def _make_item(
    text: str,
    *,
    user_data: str | None = None,
    muted: bool = False,
    tooltip: str | None = None,
) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if user_data is not None:
        item.setData(Qt.ItemDataRole.UserRole, user_data)
    if muted:
        item.setForeground(MUTED_COLOR)
        font = item.font()
        font.setItalic(True)
        item.setFont(font)
    if tooltip:
        item.setToolTip(tooltip)
    return item


def _configure_readonly_table(table: QTableWidget, headers: list[str]) -> None:
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)


class ReorderableTableWidget(QTableWidget):
    """QTableWidget mit sauberem Zeilen-Drag&Drop (ohne Zellen-Ueberschreiben)."""

    row_moved = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.source() is not self:
            event.ignore()
            return

        selected_rows = sorted({idx.row() for idx in self.selectedIndexes()})
        if not selected_rows:
            event.ignore()
            return
        from_row = selected_rows[0]

        drop_pos = event.position().toPoint()
        target_index = self.indexAt(drop_pos)
        indicator = self.dropIndicatorPosition()

        if (
            not target_index.isValid()
            or indicator == QAbstractItemView.DropIndicatorPosition.OnViewport
        ):
            to_row = self.rowCount() - 1
        else:
            to_row = target_index.row()
            if indicator == QAbstractItemView.DropIndicatorPosition.BelowItem:
                to_row += 1
            if from_row < to_row:
                to_row -= 1

        to_row = max(0, min(to_row, self.rowCount() - 1))
        event.ignore()
        if from_row != to_row:
            self.row_moved.emit(from_row, to_row)


class _SingleDnsEnrichWorker(QThread):
    """Loest FQDN & IP fuer einen einzelnen HostName im Hintergrund auf."""

    result_ready = Signal(object, object)

    def __init__(self, host_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host_name = host_name

    def run(self) -> None:
        fqdn, ip_addr = resolve_fqdn_and_ip(self._host_name)
        self.result_ready.emit(fqdn, ip_addr)


class _BulkDnsEnrichWorker(QThread):
    """Loest FQDN & IP fuer mehrere markierte Hosts parallel im Hintergrund auf."""

    result_ready = Signal(object, object)

    def __init__(
        self,
        hosts: list[HostEntry],
        target_ids: set[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._hosts = hosts
        self._target_ids = target_ids

    def run(self) -> None:
        results = enrich_hosts_dns(self._hosts)
        self.result_ready.emit(self._target_ids, results)


class SSHCnfgrWindow(QMainWindow):
    """Qt6 Hauptfenster fuer SSHCnfgr mit Hosts-, Gruppen-, Identity- und Vorschau-Tab."""

    def __init__(self, db: HostDatabase | None = None) -> None:
        super().__init__()
        self.setWindowTitle("SSHCnfgr — SSH Config Manager")
        self.resize(1180, 760)
        self.setMinimumSize(860, 560)

        self.db: HostDatabase = db if db is not None else load_database()
        self.selected_host_id: str | None = None
        self._selected_host_ids: set[str] = set()
        self.selected_group_name: str | None = None
        self.selected_identity_name: str | None = None
        self._single_dns_worker: _SingleDnsEnrichWorker | None = None
        self._bulk_dns_worker: _BulkDnsEnrichWorker | None = None

        self._build_menu_and_toolbar()
        self._build_central_ui()
        self._refresh_all()
        self._set_status("Bereit")

    def _build_menu_and_toolbar(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&Datei")
        tools_menu = menu_bar.addMenu("&Werkzeuge")

        self.act_import = QAction("SSH-Config &importieren…", self)
        self.act_import.setShortcut(QKeySequence("Ctrl+I"))
        self.act_import.triggered.connect(self.action_import_config)

        self.act_generate = QAction("Config &generieren", self)
        self.act_generate.setShortcut(QKeySequence("Ctrl+G"))
        self.act_generate.triggered.connect(self.action_generate_config)

        self.act_export_as = QAction("Config &exportieren unter…", self)
        self.act_export_as.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self.act_export_as.triggered.connect(self.action_export_config_as)

        self.act_quit = QAction("&Beenden", self)
        self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_quit.triggered.connect(self.close)

        file_menu.addAction(self.act_import)
        file_menu.addAction(self.act_generate)
        file_menu.addAction(self.act_export_as)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        self.act_dedup = QAction("&Dubletten pruefen…", self)
        self.act_dedup.setShortcut(QKeySequence("Ctrl+U"))
        self.act_dedup.triggered.connect(self.action_open_dedup)

        self.act_scan_identities = QAction("Identities aus ~/.ssh &scannen", self)
        self.act_scan_identities.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self.act_scan_identities.triggered.connect(self.action_scan_identities)

        tools_menu.addAction(self.act_dedup)
        tools_menu.addAction(self.act_scan_identities)

        toolbar = QToolBar("Hauptaktionen", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction(self.act_import)
        toolbar.addAction(self.act_generate)
        toolbar.addSeparator()
        toolbar.addAction(self.act_dedup)
        toolbar.addAction(self.act_scan_identities)

    def _build_central_ui(self) -> None:
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_hosts_tab(), "Hosts")
        self.tabs.addTab(self._build_groups_tab(), "Gruppen")
        self.tabs.addTab(self._build_identities_tab(), "Identities")
        self.tabs.addTab(self._build_preview_tab(), "Config-Vorschau")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

    # ------------------------------------------------------------------
    # Tab 1: Hosts
    # ------------------------------------------------------------------
    def _build_hosts_tab(self) -> QWidget:
        tab = QWidget(self)
        root_layout = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Orientation.Horizontal, tab)

        # Linke Seite: Suche + Host-Tabelle + Listen-Buttons
        left_widget = QWidget(splitter)
        left_layout = QVBoxLayout(left_widget)

        filter_row = QHBoxLayout()
        self.host_search_input = QLineEdit(left_widget)
        self.host_search_input.setPlaceholderText(
            "Suchen (Alias, HostName, IP, User, Gruppe, Tag)…"
        )
        self.host_search_input.setClearButtonEnabled(True)
        self.host_search_input.textChanged.connect(self._refresh_hosts_table)

        self.host_only_active_cb = QCheckBox("Nur aktive", left_widget)
        self.host_only_active_cb.toggled.connect(self._refresh_hosts_table)

        filter_row.addWidget(self.host_search_input, stretch=1)
        filter_row.addWidget(self.host_only_active_cb)
        left_layout.addLayout(filter_row)

        self.hosts_table = QTableWidget(left_widget)
        _configure_readonly_table(
            self.hosts_table,
            ["Alias", "HostName", "IP", "User", "Port", "Identity", "Gruppen", "Aktiv"],
        )
        # Mehrfachauswahl (Ctrl+Klick, Shift+Klick, Ctrl+A) + Rechtsklick-Menue
        self.hosts_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.hosts_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.hosts_table.customContextMenuRequested.connect(self._show_hosts_context_menu)
        self.hosts_table.itemSelectionChanged.connect(self._on_host_selection_changed)
        left_layout.addWidget(self.hosts_table, stretch=1)

        list_btn_row = QHBoxLayout()
        self.btn_host_new = QPushButton("Neu", left_widget)
        self.btn_host_new.setShortcut(QKeySequence("Ctrl+N"))
        self.btn_host_new.clicked.connect(self.action_new_host)

        self.btn_host_toggle = QPushButton("Aktiv umschalten", left_widget)
        self.btn_host_toggle.clicked.connect(self.action_toggle_host_enabled)

        self.btn_host_delete = QPushButton("Loeschen", left_widget)
        self.btn_host_delete.clicked.connect(self.action_delete_host)

        self.btn_host_dedup = QPushButton("Dubletten…", left_widget)
        self.btn_host_dedup.clicked.connect(self.action_open_dedup)

        list_btn_row.addWidget(self.btn_host_new)
        list_btn_row.addWidget(self.btn_host_toggle)
        list_btn_row.addWidget(self.btn_host_delete)
        list_btn_row.addStretch(1)
        list_btn_row.addWidget(self.btn_host_dedup)
        left_layout.addLayout(list_btn_row)

        # Sammel-Aktionen fuer 1 oder mehrere markierte Hosts
        bulk_box = QGroupBox("Sammel-Aktionen (Ctrl/Shift-Klick, Ctrl+A)", left_widget)
        bulk_layout = QVBoxLayout(bulk_box)

        self.lbl_bulk_selection = QLabel("Keine Auswahl", bulk_box)
        bulk_layout.addWidget(self.lbl_bulk_selection)

        bulk_group_row = QHBoxLayout()
        self.bulk_group_combo = QComboBox(bulk_box)
        self.btn_bulk_add_group = QPushButton("+ Gruppe", bulk_box)
        self.btn_bulk_add_group.setToolTip("Markierte Hosts zur gewaehlten Gruppe hinzufuegen")
        self.btn_bulk_add_group.clicked.connect(
            lambda: self.action_bulk_add_group(as_primary=False)
        )
        self.btn_bulk_primary_group = QPushButton("Als 1. Gruppe", bulk_box)
        self.btn_bulk_primary_group.setToolTip(
            "Gewaehlte Gruppe als erste/primaere Gruppe setzen (bestimmt Sortierung in VS Code)"
        )
        self.btn_bulk_primary_group.clicked.connect(
            lambda: self.action_bulk_add_group(as_primary=True)
        )
        self.btn_bulk_remove_group = QPushButton("- Gruppe", bulk_box)
        self.btn_bulk_remove_group.setToolTip("Markierte Hosts aus der gewaehlten Gruppe entfernen")
        self.btn_bulk_remove_group.clicked.connect(self.action_bulk_remove_group)

        bulk_group_row.addWidget(self.bulk_group_combo, stretch=1)
        bulk_group_row.addWidget(self.btn_bulk_add_group)
        bulk_group_row.addWidget(self.btn_bulk_primary_group)
        bulk_group_row.addWidget(self.btn_bulk_remove_group)
        bulk_layout.addLayout(bulk_group_row)

        bulk_state_row = QHBoxLayout()
        self.btn_bulk_enable = QPushButton("Alle aktivieren", bulk_box)
        self.btn_bulk_enable.clicked.connect(lambda: self.action_bulk_set_enabled(True))
        self.btn_bulk_disable = QPushButton("Alle deaktivieren", bulk_box)
        self.btn_bulk_disable.clicked.connect(lambda: self.action_bulk_set_enabled(False))
        self.btn_bulk_aliases = QPushButton("Aliase generieren", bulk_box)
        self.btn_bulk_aliases.setToolTip(
            "Benennt markierte Hosts nach dem Schema USER@kurzname (oder USER@ip) um"
        )
        self.btn_bulk_aliases.clicked.connect(self.action_bulk_generate_aliases)
        self.btn_bulk_dns_enrich = QPushButton("DNS anreichern", bulk_box)
        self.btn_bulk_dns_enrich.setToolTip(
            "Ergaenzt vollen FQDN (bei Kurznamen/IPs) und IP-Adresse per DNS"
        )
        self.btn_bulk_dns_enrich.clicked.connect(self.action_bulk_dns_enrich)
        bulk_state_row.addWidget(self.btn_bulk_enable)
        bulk_state_row.addWidget(self.btn_bulk_disable)
        bulk_state_row.addWidget(self.btn_bulk_aliases)
        bulk_state_row.addWidget(self.btn_bulk_dns_enrich)
        bulk_state_row.addStretch(1)
        bulk_layout.addLayout(bulk_state_row)

        left_layout.addWidget(bulk_box)

        # Rechte Seite: Scrollbares Detailformular + Extra-Optionen
        right_scroll = QScrollArea(splitter)
        right_scroll.setWidgetResizable(True)
        right_container = QWidget(right_scroll)
        right_layout = QVBoxLayout(right_container)

        details_group = QGroupBox("Host Details", right_container)
        form = QFormLayout(details_group)

        alias_row = QHBoxLayout()
        self.in_host_name_alias = QLineEdit(details_group)
        self.in_host_name_alias.setPlaceholderText("z. B. baer@sdvdmg-mongodb")
        self.btn_generate_alias = QPushButton("Name generieren", details_group)
        self.btn_generate_alias.setToolTip(
            "Erzeugt Alias im Format USER@kurzname (oder USER@ip) fuer VS Code"
        )
        self.btn_generate_alias.clicked.connect(self.action_generate_single_alias)
        alias_row.addWidget(self.in_host_name_alias, stretch=1)
        alias_row.addWidget(self.btn_generate_alias)

        hostname_row = QHBoxLayout()
        self.in_host_hostname = QLineEdit(details_group)
        self.in_host_hostname.setPlaceholderText("FQDN oder IP")
        self.btn_enrich_single = QPushButton("DNS (FQDN/IP)", details_group)
        self.btn_enrich_single.setToolTip(
            "Loest HostName per DNS auf: ergaenzt vollen FQDN und IP-Adresse"
        )
        self.btn_enrich_single.clicked.connect(self.action_enrich_single_host)
        hostname_row.addWidget(self.in_host_hostname, stretch=1)
        hostname_row.addWidget(self.btn_enrich_single)

        self.in_host_ip = QLineEdit(details_group)
        self.in_host_ip.setPlaceholderText(
            "optional (z. B. per DNS ermittelt, als # IP: in Config)"
        )

        self.in_host_user = QLineEdit(details_group)
        self.in_host_user.setPlaceholderText("optional (leer = Gruppe/Global/System)")

        self.in_host_port = QLineEdit(details_group)
        self.in_host_port.setPlaceholderText("optional (leer = 22 / Gruppe / Global)")

        self.in_host_identity = QComboBox(details_group)

        id_file_row = QHBoxLayout()
        self.in_host_identity_file = QLineEdit(details_group)
        self.in_host_identity_file.setPlaceholderText("optionaler direkter Key-Pfad")
        btn_pick_key = QPushButton("…", details_group)
        btn_pick_key.setMaximumWidth(36)
        btn_pick_key.setToolTip("Key-Datei auswaehlen")
        btn_pick_key.clicked.connect(self._pick_host_identity_file)
        id_file_row.addWidget(self.in_host_identity_file, stretch=1)
        id_file_row.addWidget(btn_pick_key)

        self.in_host_groups = QLineEdit(details_group)
        self.in_host_groups.setPlaceholderText(
            "Kommagetrennt, z. B. prod, db (erste Gruppe bestimmt die Sortierung)"
        )

        self.in_host_tags = QLineEdit(details_group)
        self.in_host_tags.setPlaceholderText("Kommagetrennt, z. B. k8s, web")

        self.in_host_enabled = QCheckBox(
            "Aktiv (in generierter OpenSSH-Config ausgeben)", details_group
        )
        self.in_host_enabled.setChecked(True)

        self.lbl_host_effective = QLabel("", details_group)
        self.lbl_host_effective.setWordWrap(True)

        form.addRow("Alias (Host):", alias_row)
        form.addRow("HostName:", hostname_row)
        form.addRow("IP (Info):", self.in_host_ip)
        form.addRow("User:", self.in_host_user)
        form.addRow("Port:", self.in_host_port)
        form.addRow("Identity Profile:", self.in_host_identity)
        form.addRow("IdentityFile:", id_file_row)
        form.addRow("Gruppen:", self.in_host_groups)
        form.addRow("Tags:", self.in_host_tags)
        form.addRow("", self.in_host_enabled)
        form.addRow("Effektiv:", self.lbl_host_effective)

        right_layout.addWidget(details_group)

        # Extra-Options Editor (Key / Value)
        extra_group = QGroupBox(
            "Extra SSH-Optionen (z. B. ProxyJump, IdentityAgent)", right_container
        )
        extra_layout = QVBoxLayout(extra_group)

        self.extra_options_table = QTableWidget(0, 2, extra_group)
        self.extra_options_table.setHorizontalHeaderLabels(["Direktive", "Wert"])
        self.extra_options_table.verticalHeader().setVisible(False)
        self.extra_options_table.horizontalHeader().setStretchLastSection(True)
        self.extra_options_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.extra_options_table.setMinimumHeight(130)
        extra_layout.addWidget(self.extra_options_table)

        extra_btn_row = QHBoxLayout()
        btn_add_extra = QPushButton("+ Option", extra_group)
        btn_add_extra.clicked.connect(self._add_extra_option_row)
        btn_rm_extra = QPushButton("- Entfernen", extra_group)
        btn_rm_extra.clicked.connect(self._remove_extra_option_row)
        extra_btn_row.addWidget(btn_add_extra)
        extra_btn_row.addWidget(btn_rm_extra)
        extra_btn_row.addStretch(1)
        extra_layout.addLayout(extra_btn_row)

        right_layout.addWidget(extra_group)

        save_row = QHBoxLayout()
        self.btn_host_save = QPushButton("Speichern", right_container)
        self.btn_host_save.setShortcut(QKeySequence("Ctrl+S"))
        self.btn_host_save.clicked.connect(self.action_save_host)

        self.btn_host_reset = QPushButton("Zuruecksetzen", right_container)
        self.btn_host_reset.clicked.connect(self._reset_host_form)

        save_row.addWidget(self.btn_host_save)
        save_row.addWidget(self.btn_host_reset)
        save_row.addStretch(1)
        right_layout.addLayout(save_row)
        right_layout.addStretch(1)

        right_scroll.setWidget(right_container)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_scroll)
        splitter.setSizes([580, 560])
        root_layout.addWidget(splitter)
        return tab

    # ------------------------------------------------------------------
    # Tab 2: Gruppen (mit Drag & Drop Reihenfolge & Match-Defaults)
    # ------------------------------------------------------------------
    def _build_groups_tab(self) -> QWidget:
        tab = QWidget(self)
        root_layout = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Orientation.Horizontal, tab)

        left_widget = QWidget(splitter)
        left_layout = QVBoxLayout(left_widget)

        hint_lbl = QLabel(
            "Tipp: Gruppen per Drag & Drop (oder ▲ / ▼) anordnen — bestimmt die Reihenfolge "
            "in config.generated und VS Code.",
            left_widget,
        )
        hint_lbl.setWordWrap(True)
        left_layout.addWidget(hint_lbl)

        self.groups_table = ReorderableTableWidget(left_widget)
        _configure_readonly_table(
            self.groups_table,
            ["#", "Gruppe", "Beschreibung", "Identity", "User", "Port", "Extra", "Hosts"],
        )
        self.groups_table.setColumnWidth(0, 36)
        self.groups_table.itemSelectionChanged.connect(self._on_group_selection_changed)
        self.groups_table.row_moved.connect(self._on_group_row_moved)
        left_layout.addWidget(self.groups_table, stretch=1)

        group_list_btns = QHBoxLayout()
        btn_new_group = QPushButton("Neue Gruppe", left_widget)
        btn_new_group.clicked.connect(self.action_new_group)
        self.btn_group_up = QPushButton("▲ Hoch", left_widget)
        self.btn_group_up.clicked.connect(self.action_move_group_up)
        self.btn_group_down = QPushButton("▼ Runter", left_widget)
        self.btn_group_down.clicked.connect(self.action_move_group_down)
        btn_del_group = QPushButton("Loeschen", left_widget)
        btn_del_group.clicked.connect(self.action_delete_group)
        group_list_btns.addWidget(btn_new_group)
        group_list_btns.addWidget(self.btn_group_up)
        group_list_btns.addWidget(self.btn_group_down)
        group_list_btns.addStretch(1)
        group_list_btns.addWidget(btn_del_group)
        left_layout.addLayout(group_list_btns)

        right_scroll = QScrollArea(splitter)
        right_scroll.setWidgetResizable(True)
        right_widget = QWidget(right_scroll)
        right_layout = QVBoxLayout(right_widget)

        box = QGroupBox("Gruppen-Details & Match-Defaults", right_widget)
        form = QFormLayout(box)

        self.in_group_name = QLineEdit(box)
        self.in_group_name.setPlaceholderText("z. B. prod")
        self.in_group_desc = QLineEdit(box)
        self.in_group_desc.setPlaceholderText("optionale Beschreibung")
        self.in_group_identity = QComboBox(box)
        self.in_group_user = QLineEdit(box)
        self.in_group_user.setPlaceholderText("optionaler Default-User fuer Match-Regel")
        self.in_group_port = QLineEdit(box)
        self.in_group_port.setPlaceholderText("optionaler Default-Port (1-65535)")

        form.addRow("Name:", self.in_group_name)
        form.addRow("Beschreibung:", self.in_group_desc)
        form.addRow("Default-Identity:", self.in_group_identity)
        form.addRow("Default-User:", self.in_group_user)
        form.addRow("Default-Port:", self.in_group_port)
        right_layout.addWidget(box)

        extra_group = QGroupBox(
            "Gruppen Extra-Optionen (Match originalhost, z. B. IdentitiesOnly, ProxyJump)",
            right_widget,
        )
        extra_layout = QVBoxLayout(extra_group)
        self.group_extra_options_table = QTableWidget(0, 2, extra_group)
        self.group_extra_options_table.setHorizontalHeaderLabels(["Direktive", "Wert"])
        self.group_extra_options_table.verticalHeader().setVisible(False)
        self.group_extra_options_table.horizontalHeader().setStretchLastSection(True)
        self.group_extra_options_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.group_extra_options_table.setMinimumHeight(130)
        extra_layout.addWidget(self.group_extra_options_table)

        g_extra_btns = QHBoxLayout()
        btn_g_add_extra = QPushButton("+ Option", extra_group)
        btn_g_add_extra.clicked.connect(self._add_group_extra_option_row)
        btn_g_rm_extra = QPushButton("- Entfernen", extra_group)
        btn_g_rm_extra.clicked.connect(self._remove_group_extra_option_row)
        g_extra_btns.addWidget(btn_g_add_extra)
        g_extra_btns.addWidget(btn_g_rm_extra)
        g_extra_btns.addStretch(1)
        extra_layout.addLayout(g_extra_btns)
        right_layout.addWidget(extra_group)

        btn_save_group = QPushButton("Gruppe speichern", right_widget)
        btn_save_group.clicked.connect(self.action_save_group)
        right_layout.addWidget(btn_save_group)
        right_layout.addStretch(1)

        right_scroll.setWidget(right_widget)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_scroll)
        splitter.setSizes([640, 480])
        root_layout.addWidget(splitter)
        return tab

    # ------------------------------------------------------------------
    # Tab 3: Identities
    # ------------------------------------------------------------------
    def _build_identities_tab(self) -> QWidget:
        tab = QWidget(self)
        root_layout = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Orientation.Horizontal, tab)

        left_widget = QWidget(splitter)
        left_layout = QVBoxLayout(left_widget)

        self.identities_table = QTableWidget(left_widget)
        _configure_readonly_table(
            self.identities_table,
            ["Name", "IdentityFile", "Public Key", "Quelle", "Aktiv"],
        )
        self.identities_table.itemSelectionChanged.connect(self._on_identity_selection_changed)
        left_layout.addWidget(self.identities_table, stretch=1)

        id_list_btns = QHBoxLayout()
        btn_scan = QPushButton("Scan ~/.ssh", left_widget)
        btn_scan.clicked.connect(self.action_scan_identities)
        btn_new_id = QPushButton("Neu", left_widget)
        btn_new_id.clicked.connect(self.action_new_identity)
        btn_toggle_id = QPushButton("Aktiv umschalten", left_widget)
        btn_toggle_id.clicked.connect(self.action_toggle_identity_enabled)
        btn_del_id = QPushButton("Loeschen", left_widget)
        btn_del_id.clicked.connect(self.action_delete_identity)
        id_list_btns.addWidget(btn_scan)
        id_list_btns.addWidget(btn_new_id)
        id_list_btns.addWidget(btn_toggle_id)
        id_list_btns.addWidget(btn_del_id)
        id_list_btns.addStretch(1)
        left_layout.addLayout(id_list_btns)

        right_widget = QWidget(splitter)
        right_layout = QVBoxLayout(right_widget)
        box = QGroupBox("Identity-Profil", right_widget)
        form = QFormLayout(box)

        self.in_id_name = QLineEdit(box)
        self.in_id_name.setPlaceholderText("z. B. id_ed25519")

        id_path_row = QHBoxLayout()
        self.in_id_file = QLineEdit(box)
        self.in_id_file.setPlaceholderText("Pfad zur Key-Datei")
        btn_pick_id_file = QPushButton("…", box)
        btn_pick_id_file.setMaximumWidth(36)
        btn_pick_id_file.clicked.connect(self._pick_profile_identity_file)
        id_path_row.addWidget(self.in_id_file, stretch=1)
        id_path_row.addWidget(btn_pick_id_file)

        self.in_id_source = QLineEdit(box)
        self.in_id_source.setPlaceholderText("manual / local-ssh")
        self.in_id_enabled = QCheckBox("Aktiv", box)
        self.in_id_enabled.setChecked(True)

        form.addRow("Name:", self.in_id_name)
        form.addRow("IdentityFile:", id_path_row)
        form.addRow("Quelle:", self.in_id_source)
        form.addRow("", self.in_id_enabled)
        right_layout.addWidget(box)

        btn_save_id = QPushButton("Identity speichern", right_widget)
        btn_save_id.clicked.connect(self.action_save_identity)
        right_layout.addWidget(btn_save_id)
        right_layout.addStretch(1)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([640, 460])
        root_layout.addWidget(splitter)
        return tab

    # ------------------------------------------------------------------
    # Tab 4: Config-Vorschau
    # ------------------------------------------------------------------
    def _build_preview_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        btn_row = QHBoxLayout()
        btn_refresh = QPushButton("Aktualisieren", tab)
        btn_refresh.clicked.connect(self._refresh_preview)
        btn_write = QPushButton("In config.generated schreiben", tab)
        btn_write.clicked.connect(self.action_generate_config)
        btn_export = QPushButton("Exportieren unter…", tab)
        btn_export.clicked.connect(self.action_export_config_as)
        btn_row.addWidget(btn_refresh)
        btn_row.addWidget(btn_write)
        btn_row.addWidget(btn_export)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.preview_edit = QPlainTextEdit(tab)
        self.preview_edit.setReadOnly(True)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self.preview_edit.setFont(mono)
        layout.addWidget(self.preview_edit, stretch=1)
        return tab

    # ------------------------------------------------------------------
    # Refresh & Hilfsmethoden
    # ------------------------------------------------------------------
    def _set_status(self, message: str) -> None:
        dup_count = len(find_duplicate_groups(self.db, include_inactive=False))
        summary = (
            f"Hosts: {len(self.db.hosts)} | Gruppen: {len(self.db.groups)} | "
            f"Identities: {len(self.db.identities)} | Dubletten: {dup_count}"
        )
        self.statusBar().showMessage(f"{message}   —   {summary}")

    def _refresh_all(self) -> None:
        self._refresh_identity_combos()
        self._refresh_bulk_group_combo()
        self._refresh_hosts_table()
        self._refresh_groups_table()
        self._refresh_identities_table()
        self._refresh_preview()
        self._update_dedup_badge()
        self._update_bulk_controls()

    def _refresh_bulk_group_combo(self) -> None:
        combo = self.bulk_group_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        try:
            combo.clear()
            groups = self.db.ordered_groups()
            if not groups:
                combo.addItem("(keine Gruppen definiert)", None)
            else:
                for group in groups:
                    combo.addItem(group.name, group.name)
                if previous:
                    idx = combo.findData(previous)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
        finally:
            combo.blockSignals(False)

    def selected_host_ids(self) -> list[str]:
        """Liefert die IDs aller aktuell in der Host-Tabelle markierten Zeilen."""
        ids: list[str] = []
        selection_model = self.hosts_table.selectionModel()
        if selection_model is None:
            return ids
        for idx in selection_model.selectedRows(0):
            item = self.hosts_table.item(idx.row(), 0)
            if item is not None:
                host_id = item.data(Qt.ItemDataRole.UserRole)
                if host_id:
                    ids.append(str(host_id))
        return ids

    def _update_bulk_controls(self) -> None:
        count = len(self._selected_host_ids)
        has_selection = count > 0
        has_group = self.bulk_group_combo.currentData() is not None

        if count == 0:
            self.lbl_bulk_selection.setText("Keine Hosts markiert")
        elif count == 1:
            self.lbl_bulk_selection.setText("1 Host markiert")
        else:
            self.lbl_bulk_selection.setText(f"{count} Hosts markiert")

        self.btn_bulk_enable.setEnabled(has_selection)
        self.btn_bulk_disable.setEnabled(has_selection)
        self.btn_bulk_aliases.setEnabled(has_selection)
        bulk_dns_busy = self._bulk_dns_worker is not None and self._bulk_dns_worker.isRunning()
        self.btn_bulk_dns_enrich.setEnabled(has_selection and not bulk_dns_busy)
        self.btn_bulk_add_group.setEnabled(has_selection and has_group)
        self.btn_bulk_primary_group.setEnabled(has_selection and has_group)
        self.btn_bulk_remove_group.setEnabled(has_selection and has_group)
        self.btn_host_toggle.setEnabled(has_selection)
        self.btn_host_delete.setEnabled(has_selection)

        # Bei Mehrfachauswahl Einzelformular-Speichern deaktivieren, um Versehen zu vermeiden.
        multi = count > 1
        self.btn_host_save.setEnabled(not multi)
        self.btn_host_reset.setEnabled(not multi)

    def _update_dedup_badge(self) -> None:
        dup_count = len(find_duplicate_groups(self.db, include_inactive=False))
        label = f"Dubletten ({dup_count})…" if dup_count else "Dubletten…"
        self.btn_host_dedup.setText(label)

    def _populate_identity_combo(self, combo: QComboBox, current_value: str | None) -> None:
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("(keine)", None)
            for identity in self.db.sorted_identities():
                suffix = "" if identity.enabled else " (deaktiviert)"
                combo.addItem(f"{identity.name}{suffix}", identity.name)
            if current_value:
                idx = combo.findData(current_value)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.addItem(f"{current_value} (unbekannt)", current_value)
                    combo.setCurrentIndex(combo.count() - 1)
            else:
                combo.setCurrentIndex(0)
        finally:
            combo.blockSignals(False)

    def _refresh_identity_combos(self) -> None:
        host_current = self.in_host_identity.currentData()
        group_current = self.in_group_identity.currentData()
        self._populate_identity_combo(self.in_host_identity, host_current)
        self._populate_identity_combo(self.in_group_identity, group_current)

    def _host_matches_filter(self, host: HostEntry, needle: str, only_active: bool) -> bool:
        if only_active and not host.enabled:
            return False
        if not needle:
            return True
        haystack = " ".join(
            [
                host.name,
                host.host_name,
                host.ip or "",
                host.user or "",
                self.db.resolve_user(host) or "",
                *host.groups,
                *host.tags,
            ]
        ).lower()
        return needle in haystack

    def _refresh_hosts_table(self) -> None:
        needle = self.host_search_input.text().strip().lower()
        only_active = self.host_only_active_cb.isChecked()
        hosts = [
            h
            for h in self.db.ordered_hosts_by_group()
            if self._host_matches_filter(h, needle, only_active)
        ]

        table = self.hosts_table
        table.setSortingEnabled(False)
        table.blockSignals(True)
        try:
            table.setRowCount(len(hosts))
            selected_rows: list[int] = []
            target_ids = (
                set(self._selected_host_ids)
                if self._selected_host_ids
                else ({self.selected_host_id} if self.selected_host_id else set())
            )
            for row, host in enumerate(hosts):
                if host.id in target_ids:
                    selected_rows.append(row)

                eff_user = self.db.resolve_user(host)
                user_muted = host.user is None and eff_user is not None
                user_text = host.user or eff_user or ""

                eff_port = self.db.resolve_port(host)
                port_muted = host.port is None
                port_text = str(host.port if host.port is not None else eff_port)

                identity_text, identity_muted, identity_tip = self._describe_identity(host)

                table.setItem(row, 0, _make_item(host.name, user_data=host.id))
                table.setItem(row, 1, _make_item(host.host_name))
                table.setItem(row, 2, _make_item(host.ip or "", muted=bool(host.ip)))
                table.setItem(
                    row,
                    3,
                    _make_item(
                        user_text,
                        muted=user_muted,
                        tooltip="Geerbt via Gruppe oder Host *" if user_muted else None,
                    ),
                )
                table.setItem(
                    row,
                    4,
                    _make_item(
                        port_text,
                        muted=port_muted,
                        tooltip="Effektiver Port (Gruppe/Global/Default)" if port_muted else None,
                    ),
                )
                table.setItem(
                    row,
                    5,
                    _make_item(identity_text, muted=identity_muted, tooltip=identity_tip),
                )
                table.setItem(row, 6, _make_item(", ".join(host.groups)))
                table.setItem(
                    row,
                    7,
                    _make_item("Ja" if host.enabled else "Nein", muted=not host.enabled),
                )

            selection_model = table.selectionModel()
            if selection_model is not None and selected_rows:
                flags = (
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows
                )
                for row in selected_rows:
                    selection_model.select(table.model().index(row, 0), flags)
        finally:
            table.blockSignals(False)

        self._selected_host_ids = set(self.selected_host_ids())
        self._update_bulk_controls()

    def _describe_identity(self, host: HostEntry) -> tuple[str, bool, str | None]:
        if host.identity_file:
            return host.identity_file, False, "Explizite IdentityFile am Host"
        if host.identity:
            return host.identity, False, "Identity-Profil am Host"
        resolved = self.db.resolve_identity_file(host)
        if resolved:
            return resolved, True, "Geerbt via Gruppe oder Host *"
        agent = self.db.resolve_identity_agent(host)
        if agent:
            return f"agent:{agent}", True, "Effektiver IdentityAgent"
        return "", False, None

    def _refresh_groups_table(self) -> None:
        groups = self.db.ordered_groups()
        table = self.groups_table
        table.blockSignals(True)
        try:
            table.setRowCount(len(groups))
            selected_row = -1
            for row, group in enumerate(groups):
                if group.name == self.selected_group_name:
                    selected_row = row
                host_count = sum(1 for h in self.db.hosts if group.name in h.groups)
                extra_summary = ", ".join(
                    f"{k}={v}"
                    for k, v in sorted(group.extra_options.items(), key=lambda p: p[0].lower())
                )
                table.setItem(row, 0, _make_item(str(row + 1), user_data=group.name))
                table.setItem(row, 1, _make_item(group.name, user_data=group.name))
                table.setItem(row, 2, _make_item(group.description))
                table.setItem(row, 3, _make_item(group.identity or ""))
                table.setItem(row, 4, _make_item(group.user or ""))
                table.setItem(row, 5, _make_item(str(group.port) if group.port is not None else ""))
                table.setItem(row, 6, _make_item(extra_summary))
                table.setItem(row, 7, _make_item(str(host_count)))
            if selected_row >= 0:
                table.selectRow(selected_row)
        finally:
            table.blockSignals(False)

    def _refresh_identities_table(self) -> None:
        identities = self.db.sorted_identities()
        table = self.identities_table
        table.blockSignals(True)
        try:
            table.setRowCount(len(identities))
            selected_row = -1
            for row, identity in enumerate(identities):
                if identity.name == self.selected_identity_name:
                    selected_row = row
                table.setItem(row, 0, _make_item(identity.name, user_data=identity.name))
                table.setItem(row, 1, _make_item(identity.identity_file))
                table.setItem(row, 2, _make_item(identity.public_key_preview or ""))
                table.setItem(row, 3, _make_item(identity.source))
                table.setItem(
                    row,
                    4,
                    _make_item("Ja" if identity.enabled else "Nein", muted=not identity.enabled),
                )
            if selected_row >= 0:
                table.selectRow(selected_row)
        finally:
            table.blockSignals(False)

    def _refresh_preview(self) -> None:
        self.preview_edit.setPlainText(generate_config(self.db))

    def _on_tab_changed(self, index: int) -> None:
        if index == 3:
            self._refresh_preview()

    # ------------------------------------------------------------------
    # Host-Formular & Sammel-Aktionen
    # ------------------------------------------------------------------
    def _on_host_selection_changed(self) -> None:
        selected_ids = self.selected_host_ids()
        self._selected_host_ids = set(selected_ids)
        self._update_bulk_controls()

        if len(selected_ids) == 1:
            host = self.db.get_by_id(selected_ids[0])
            if host is not None:
                self.selected_host_id = host.id
                self._load_host_into_form(host)
            return

        self.selected_host_id = None
        if len(selected_ids) > 1:
            self.lbl_host_effective.setText(
                f"{len(selected_ids)} Hosts markiert — Sammel-Aktionen links oder Rechtsklick."
            )

    def _show_hosts_context_menu(self, pos: QPoint) -> None:
        selected_ids = self.selected_host_ids()
        if not selected_ids:
            return
        count = len(selected_ids)
        menu = QMenu(self)

        act_enable = menu.addAction(f"Aktivieren ({count})")
        act_enable.triggered.connect(lambda: self.action_bulk_set_enabled(True))

        act_disable = menu.addAction(f"Deaktivieren ({count})")
        act_disable.triggered.connect(lambda: self.action_bulk_set_enabled(False))

        menu.addSeparator()

        groups = self.db.ordered_groups()
        if groups:
            add_menu = menu.addMenu("Zu Gruppe hinzufuegen")
            primary_menu = menu.addMenu("Als 1. Gruppe setzen")
            remove_menu = menu.addMenu("Aus Gruppe entfernen")
            for group in groups:
                g_name = group.name
                a1 = add_menu.addAction(g_name)
                a1.triggered.connect(
                    lambda _checked=False, name=g_name: self.action_bulk_add_group(
                        group_name=name, as_primary=False
                    )
                )
                a2 = primary_menu.addAction(g_name)
                a2.triggered.connect(
                    lambda _checked=False, name=g_name: self.action_bulk_add_group(
                        group_name=name, as_primary=True
                    )
                )
                a3 = remove_menu.addAction(g_name)
                a3.triggered.connect(
                    lambda _checked=False, name=g_name: self.action_bulk_remove_group(
                        group_name=name
                    )
                )

        identities = self.db.sorted_identities()
        id_menu = menu.addMenu("Identity zuweisen")
        act_clear_id = id_menu.addAction("(keine)")
        act_clear_id.triggered.connect(lambda: self.action_bulk_set_identity(None))
        for identity in identities:
            i_name = identity.name
            ai = id_menu.addAction(i_name)
            ai.triggered.connect(
                lambda _checked=False, name=i_name: self.action_bulk_set_identity(name)
            )

        menu.addSeparator()
        act_aliases = menu.addAction(f"Aliase generieren (USER@host) ({count})…")
        act_aliases.triggered.connect(self.action_bulk_generate_aliases)
        act_dns = menu.addAction(f"Per DNS anreichern (FQDN/IP) ({count})")
        act_dns.triggered.connect(self.action_bulk_dns_enrich)

        menu.addSeparator()
        act_delete = menu.addAction(f"Loeschen ({count})…")
        act_delete.triggered.connect(self.action_delete_host)

        menu.exec(self.hosts_table.viewport().mapToGlobal(pos))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._single_dns_worker is not None and self._single_dns_worker.isRunning():
            try:
                self._single_dns_worker.result_ready.disconnect(self._on_single_dns_enriched)
            except RuntimeError:
                pass
        if self._bulk_dns_worker is not None and self._bulk_dns_worker.isRunning():
            try:
                self._bulk_dns_worker.result_ready.disconnect(self._on_bulk_dns_enriched)
            except RuntimeError:
                pass
        super().closeEvent(event)

    def _load_host_into_form(self, host: HostEntry) -> None:
        self.in_host_name_alias.setText(host.name)
        self.in_host_hostname.setText(host.host_name)
        self.in_host_ip.setText(host.ip or "")
        self.in_host_user.setText(host.user or "")
        self.in_host_port.setText(str(host.port) if host.port is not None else "")
        self._populate_identity_combo(self.in_host_identity, host.identity)
        self.in_host_identity_file.setText(host.identity_file or "")
        self.in_host_groups.setText(", ".join(host.groups))
        self.in_host_tags.setText(", ".join(host.tags))
        self.in_host_enabled.setChecked(host.enabled)

        eff_user = self.db.resolve_user(host) or "-"
        eff_port = self.db.resolve_port(host)
        eff_id = self.db.resolve_identity_file(host) or (
            f"agent:{self.db.resolve_identity_agent(host)}"
            if self.db.resolve_identity_agent(host)
            else "-"
        )
        self.lbl_host_effective.setText(
            f"User: {eff_user} | Port: {eff_port} | Identity: {eff_id}"
        )

        self.extra_options_table.setRowCount(0)
        for key, value in sorted(host.extra_options.items(), key=lambda pair: pair[0].lower()):
            row = self.extra_options_table.rowCount()
            self.extra_options_table.insertRow(row)
            self.extra_options_table.setItem(row, 0, QTableWidgetItem(key))
            self.extra_options_table.setItem(row, 1, QTableWidgetItem(value))

    def _reset_host_form(self) -> None:
        if self.selected_host_id:
            host = self.db.get_by_id(self.selected_host_id)
            if host is not None:
                self._load_host_into_form(host)
                self._set_status(f"Formular zurueckgesetzt: {host.name}")
                return
        self.action_new_host()

    def _add_extra_option_row(self) -> None:
        row = self.extra_options_table.rowCount()
        self.extra_options_table.insertRow(row)
        self.extra_options_table.setItem(row, 0, QTableWidgetItem(""))
        self.extra_options_table.setItem(row, 1, QTableWidgetItem(""))
        self.extra_options_table.editItem(self.extra_options_table.item(row, 0))

    def _remove_extra_option_row(self) -> None:
        rows = sorted(
            {idx.row() for idx in self.extra_options_table.selectionModel().selectedRows()},
            reverse=True,
        )
        for row in rows:
            self.extra_options_table.removeRow(row)

    def _pick_host_identity_file(self) -> None:
        start_dir = str(Path.home() / ".ssh")
        selected, _ = QFileDialog.getOpenFileName(self, "IdentityFile auswaehlen", start_dir)
        if selected:
            self.in_host_identity_file.setText(selected)

    def _read_host_form(self) -> tuple[HostEntry, list[str]]:
        existing = self.db.get_by_id(self.selected_host_id) if self.selected_host_id else None
        host = copy.deepcopy(existing) if existing is not None else HostEntry()

        host.name = self.in_host_name_alias.text().strip()
        host.host_name = self.in_host_hostname.text().strip()
        host.ip = self.in_host_ip.text().strip() or None
        host.user = self.in_host_user.text().strip() or None

        errors: list[str] = []
        port_raw = self.in_host_port.text().strip()
        if port_raw:
            try:
                host.port = int(port_raw)
            except ValueError:
                errors.append(f"Port ist keine Zahl: {port_raw}")
        else:
            host.port = None

        identity_data = self.in_host_identity.currentData()
        host.identity = str(identity_data) if identity_data else None
        host.identity_file = self.in_host_identity_file.text().strip() or None
        host.groups = [
            item.strip() for item in self.in_host_groups.text().split(",") if item.strip()
        ]
        host.tags = [item.strip() for item in self.in_host_tags.text().split(",") if item.strip()]
        host.enabled = self.in_host_enabled.isChecked()

        extra_options: dict[str, str] = {}
        for row in range(self.extra_options_table.rowCount()):
            key_item = self.extra_options_table.item(row, 0)
            val_item = self.extra_options_table.item(row, 1)
            key = key_item.text().strip() if key_item else ""
            val = val_item.text().strip() if val_item else ""
            if not key and not val:
                continue
            if not key or not val:
                errors.append(f"Extra-Option in Zeile {row + 1} ist unvollstaendig")
                continue
            if any(ch.isspace() for ch in key):
                errors.append(f"Extra-Option '{key}' darf keine Leerzeichen enthalten")
                continue
            extra_options[key] = val
        host.extra_options = extra_options

        errors.extend(host.validate())
        return host, errors

    def action_new_host(self) -> None:
        self.selected_host_id = None
        self._selected_host_ids.clear()
        self.hosts_table.clearSelection()
        self.in_host_name_alias.clear()
        self.in_host_hostname.clear()
        self.in_host_ip.clear()
        self.in_host_user.clear()
        self.in_host_port.clear()
        self._populate_identity_combo(self.in_host_identity, None)
        self.in_host_identity_file.clear()
        self.in_host_groups.clear()
        self.in_host_tags.clear()
        self.in_host_enabled.setChecked(True)
        self.lbl_host_effective.setText("Neuer Host")
        self.extra_options_table.setRowCount(0)
        self._update_bulk_controls()
        self.in_host_name_alias.setFocus()
        self._set_status("Neuer Host: Felder ausfuellen und speichern")

    def action_save_host(self) -> None:
        candidate, errors = self._read_host_form()
        if errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(errors))
            return

        candidate_db = copy.deepcopy(self.db)
        existing = candidate_db.get_by_id(candidate.id)
        if existing is None:
            candidate_db.hosts.append(candidate)
        else:
            candidate_db.hosts[candidate_db.hosts.index(existing)] = candidate
        candidate_db.ensure_groups(candidate.groups)

        db_errors = candidate_db.validate()
        if db_errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(db_errors))
            return

        if not self._commit_db(candidate_db):
            return

        self.selected_host_id = candidate.id
        self._selected_host_ids = {candidate.id}
        self._refresh_all()
        self._load_host_into_form(candidate)
        self._set_status(f"Host gespeichert: {candidate.name}")

    def action_generate_single_alias(self) -> None:
        """Schlaegt fuer den aktuellen Host im Formular einen Alias USER@kurzname vor."""
        existing = self.db.get_by_id(self.selected_host_id) if self.selected_host_id else None
        probe = copy.deepcopy(existing) if existing is not None else HostEntry()
        probe.host_name = self.in_host_hostname.text().strip()
        probe.user = self.in_host_user.text().strip() or None
        probe.groups = [
            item.strip() for item in self.in_host_groups.text().split(",") if item.strip()
        ]
        if not probe.host_name:
            self._set_status("Bitte zuerst HostName eintragen")
            return

        suggested = suggest_host_alias(probe, self.db)
        self.in_host_name_alias.setText(suggested)
        self._set_status(f"Alias-Vorschlag: {suggested} (zum Uebernehmen Speichern klicken)")

    def action_enrich_single_host(self) -> None:
        """Loest den HostName im Formular per DNS auf und ergaenzt FQDN & IP."""
        if self._single_dns_worker is not None and self._single_dns_worker.isRunning():
            return
        host_name = self.in_host_hostname.text().strip()
        if not host_name:
            self._set_status("Bitte zuerst HostName eintragen")
            return

        self.btn_enrich_single.setEnabled(False)
        self.btn_enrich_single.setText("DNS…")
        self._set_status(f"DNS-Abfrage fuer '{host_name}'…")

        worker = _SingleDnsEnrichWorker(host_name, parent=self)
        worker.result_ready.connect(self._on_single_dns_enriched)
        worker.finished.connect(worker.deleteLater)
        self._single_dns_worker = worker
        worker.start()

    def _on_single_dns_enriched(self, fqdn: object, ip_addr: object) -> None:
        self._single_dns_worker = None
        self.btn_enrich_single.setEnabled(True)
        self.btn_enrich_single.setText("DNS (FQDN/IP)")

        fqdn_str = str(fqdn) if isinstance(fqdn, str) and fqdn else None
        ip_str = str(ip_addr) if isinstance(ip_addr, str) and ip_addr else None

        if not fqdn_str and not ip_str:
            self._set_status("DNS-Aufloesung fehlgeschlagen (Host nicht erreichbar / unbekannt)")
            return

        parts: list[str] = []
        if fqdn_str:
            self.in_host_hostname.setText(fqdn_str)
            parts.append(f"FQDN={fqdn_str}")
        if ip_str:
            self.in_host_ip.setText(ip_str)
            parts.append(f"IP={ip_str}")
        self._set_status(f"DNS ergaenzt: {', '.join(parts)} (zum Uebernehmen Speichern klicken)")

    def action_bulk_generate_aliases(self, *, skip_confirm: bool = False) -> None:
        """Benennt alle markierten Hosts nach dem Schema USER@kurzname (oder USER@ip) um."""
        target_ids = set(self.selected_host_ids())
        if not target_ids:
            self._set_status("Keine Hosts markiert")
            return

        candidate_db, renames, errors = bulk_generate_aliases(self.db, target_ids)
        if errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(errors))
            return
        if not renames:
            self._set_status("Alle markierten Hosts entsprechen bereits dem Schema USER@kurzname")
            return

        if not skip_confirm:
            preview_lines = [f"{old}  →  {new}" for old, new in renames[:8]]
            if len(renames) > 8:
                preview_lines.append(f"… (+{len(renames) - 8} weitere)")
            answer = QMessageBox.question(
                self,
                "Aliase generieren",
                f"{len(renames)} Host(s) nach Schema USER@kurzname umbenennen?\n\n"
                + "\n".join(preview_lines),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        if not self._commit_db(candidate_db):
            return

        self._selected_host_ids = target_ids
        self._refresh_all()
        if len(target_ids) == 1:
            host = self.db.get_by_id(next(iter(target_ids)))
            if host is not None:
                self._load_host_into_form(host)
        self._set_status(f"{len(renames)} Host-Alias(e) generiert")

    def action_bulk_dns_enrich(self) -> None:
        """Startet parallele DNS-Anreicherung (FQDN + IP) fuer alle markierten Hosts."""
        if self._bulk_dns_worker is not None and self._bulk_dns_worker.isRunning():
            return
        target_ids = set(self.selected_host_ids())
        if not target_ids:
            self._set_status("Keine Hosts markiert")
            return

        targets = [copy.deepcopy(h) for h in self.db.hosts if h.id in target_ids]
        if not targets:
            return

        self.btn_bulk_dns_enrich.setEnabled(False)
        self.btn_bulk_dns_enrich.setText("DNS laeuft…")
        self._set_status(f"Reiche {len(targets)} Host(s) per DNS an (FQDN & IP)…")

        worker = _BulkDnsEnrichWorker(targets, target_ids, parent=self)
        worker.result_ready.connect(self._on_bulk_dns_enriched)
        worker.finished.connect(worker.deleteLater)
        self._bulk_dns_worker = worker
        worker.start()

    def _on_bulk_dns_enriched(self, target_ids: object, results: object) -> None:
        self._bulk_dns_worker = None
        self.btn_bulk_dns_enrich.setText("DNS anreichern")
        self._update_bulk_controls()

        if not isinstance(target_ids, set) or not isinstance(results, dict):
            return
        self.apply_bulk_dns_results(target_ids, results)

    def apply_bulk_dns_results(
        self,
        target_ids: set[str],
        results: dict[str, DnsEnrichResult],
    ) -> None:
        """Uebernimmt DNS-Anreicherungsergebnisse transaktional in DB & UI."""
        candidate_db, updated, unresolved, errors = apply_dns_enrichment(
            self.db,
            target_ids,
            results,
        )
        if errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(errors))
            return

        if updated == 0:
            self._set_status(
                f"DNS-Anreicherung: keine Aenderungen ({unresolved} nicht aufloesbar)"
            )
            return

        if not self._commit_db(candidate_db):
            return

        self._selected_host_ids = set(target_ids)
        self._refresh_all()
        if len(target_ids) == 1:
            host = self.db.get_by_id(next(iter(target_ids)))
            if host is not None:
                self._load_host_into_form(host)
        self._set_status(
            f"DNS-Anreicherung: {updated} Host(s) aktualisiert ({unresolved} nicht aufloesbar)"
        )

    def action_toggle_host_enabled(self) -> None:
        target_ids = set(self.selected_host_ids())
        if not target_ids:
            self._set_status("Kein Host ausgewaehlt")
            return

        candidate_db = copy.deepcopy(self.db)
        changed = 0
        last_host: HostEntry | None = None
        for host in candidate_db.hosts:
            if host.id in target_ids:
                host.enabled = not host.enabled
                changed += 1
                last_host = host

        if not changed or not self._commit_db(candidate_db):
            return

        self._selected_host_ids = target_ids
        self._refresh_all()
        if len(target_ids) == 1 and last_host is not None:
            self._load_host_into_form(last_host)
            self._set_status(f"Host '{last_host.name}' aktiv={last_host.enabled}")
        else:
            self._set_status(f"{changed} Host(s) umgeschaltet")

    def action_bulk_set_enabled(self, enabled: bool) -> None:
        target_ids = set(self.selected_host_ids())
        if not target_ids:
            self._set_status("Keine Hosts markiert")
            return

        candidate_db = copy.deepcopy(self.db)
        changed = candidate_db.bulk_set_enabled(target_ids, enabled)
        if changed == 0:
            state = "aktiv" if enabled else "inaktiv"
            self._set_status(f"Alle {len(target_ids)} markierten Hosts sind bereits {state}")
            return

        if not self._commit_db(candidate_db):
            return

        self._selected_host_ids = target_ids
        self._refresh_all()
        if len(target_ids) == 1:
            host = self.db.get_by_id(next(iter(target_ids)))
            if host is not None:
                self._load_host_into_form(host)
        verb = "aktiviert" if enabled else "deaktiviert"
        self._set_status(f"{changed} Host(s) {verb}")

    def action_bulk_add_group(
        self,
        *,
        group_name: str | None = None,
        as_primary: bool = False,
    ) -> None:
        target_ids = set(self.selected_host_ids())
        if not target_ids:
            self._set_status("Keine Hosts markiert")
            return

        chosen = group_name if group_name is not None else self.bulk_group_combo.currentData()
        if not chosen:
            self._set_status("Bitte zuerst im Gruppen-Tab eine Gruppe anlegen")
            return
        chosen_name = str(chosen)

        candidate_db = copy.deepcopy(self.db)
        changed = candidate_db.bulk_add_group(target_ids, chosen_name, as_primary=as_primary)
        errors = candidate_db.validate()
        if errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(errors))
            return

        if changed == 0:
            self._set_status(f"Markierte Hosts sind bereits in Gruppe '{chosen_name}'")
            return

        if not self._commit_db(candidate_db):
            return

        self._selected_host_ids = target_ids
        self._refresh_all()
        if len(target_ids) == 1:
            host = self.db.get_by_id(next(iter(target_ids)))
            if host is not None:
                self._load_host_into_form(host)
        detail = "als 1. Gruppe gesetzt" if as_primary else "zugewiesen"
        self._set_status(f"{changed} Host(s): Gruppe '{chosen_name}' {detail}")

    def action_bulk_remove_group(self, *, group_name: str | None = None) -> None:
        target_ids = set(self.selected_host_ids())
        if not target_ids:
            self._set_status("Keine Hosts markiert")
            return

        chosen = group_name if group_name is not None else self.bulk_group_combo.currentData()
        if not chosen:
            self._set_status("Keine Gruppe ausgewaehlt")
            return
        chosen_name = str(chosen)

        candidate_db = copy.deepcopy(self.db)
        changed = candidate_db.bulk_remove_group(target_ids, chosen_name)
        if changed == 0:
            self._set_status(f"Keiner der markierten Hosts war in Gruppe '{chosen_name}'")
            return

        if not self._commit_db(candidate_db):
            return

        self._selected_host_ids = target_ids
        self._refresh_all()
        if len(target_ids) == 1:
            host = self.db.get_by_id(next(iter(target_ids)))
            if host is not None:
                self._load_host_into_form(host)
        self._set_status(f"{changed} Host(s) aus Gruppe '{chosen_name}' entfernt")

    def action_bulk_set_identity(self, identity_name: str | None) -> None:
        target_ids = set(self.selected_host_ids())
        if not target_ids:
            self._set_status("Keine Hosts markiert")
            return

        candidate_db = copy.deepcopy(self.db)
        changed = candidate_db.bulk_set_identity(target_ids, identity_name)
        errors = candidate_db.validate()
        if errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(errors))
            return

        if changed == 0:
            self._set_status("Keine Aenderung noetig")
            return

        if not self._commit_db(candidate_db):
            return

        self._selected_host_ids = target_ids
        self._refresh_all()
        if len(target_ids) == 1:
            host = self.db.get_by_id(next(iter(target_ids)))
            if host is not None:
                self._load_host_into_form(host)
        label = identity_name or "(keine)"
        self._set_status(f"{changed} Host(s): Identity '{label}' gesetzt")

    def action_delete_host(self) -> None:
        target_ids = set(self.selected_host_ids())
        if not target_ids:
            self._set_status("Kein Host ausgewaehlt")
            return

        targets = [h for h in self.db.hosts if h.id in target_ids]
        if not targets:
            return

        if len(targets) == 1:
            host = targets[0]
            prompt = f"Host '{host.name}' ({host.host_name}) wirklich loeschen?"
            title = "Host loeschen"
        else:
            preview = ", ".join(h.name for h in targets[:6])
            if len(targets) > 6:
                preview += f", … (+{len(targets) - 6})"
            prompt = f"{len(targets)} markierte Hosts wirklich loeschen?\n\n{preview}"
            title = "Mehrere Hosts loeschen"

        answer = QMessageBox.question(
            self,
            title,
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        candidate_db = copy.deepcopy(self.db)
        removed = candidate_db.bulk_delete_hosts(target_ids)
        if not self._commit_db(candidate_db):
            return

        self.action_new_host()
        self._refresh_all()
        self._set_status(f"{removed} Host(s) geloescht")

    # ------------------------------------------------------------------
    # Gruppen-Aktionen
    # ------------------------------------------------------------------
    def _on_group_selection_changed(self) -> None:
        selected_rows = self.groups_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        item = self.groups_table.item(selected_rows[0].row(), 1)
        if item is None:
            return
        group_name = str(item.data(Qt.ItemDataRole.UserRole))
        group = self.db.get_group_by_name(group_name)
        if group is None:
            return
        self._load_group_into_form(group)

    def _load_group_into_form(self, group: HostGroup) -> None:
        self.selected_group_name = group.name
        self.in_group_name.setText(group.name)
        self.in_group_desc.setText(group.description)
        self._populate_identity_combo(self.in_group_identity, group.identity)
        self.in_group_user.setText(group.user or "")
        self.in_group_port.setText(str(group.port) if group.port is not None else "")

        self.group_extra_options_table.setRowCount(0)
        for key, value in sorted(group.extra_options.items(), key=lambda pair: pair[0].lower()):
            row = self.group_extra_options_table.rowCount()
            self.group_extra_options_table.insertRow(row)
            self.group_extra_options_table.setItem(row, 0, QTableWidgetItem(key))
            self.group_extra_options_table.setItem(row, 1, QTableWidgetItem(value))

    def _add_group_extra_option_row(self) -> None:
        row = self.group_extra_options_table.rowCount()
        self.group_extra_options_table.insertRow(row)
        self.group_extra_options_table.setItem(row, 0, QTableWidgetItem(""))
        self.group_extra_options_table.setItem(row, 1, QTableWidgetItem(""))
        self.group_extra_options_table.editItem(self.group_extra_options_table.item(row, 0))

    def _remove_group_extra_option_row(self) -> None:
        rows = sorted(
            {idx.row() for idx in self.group_extra_options_table.selectionModel().selectedRows()},
            reverse=True,
        )
        for row in rows:
            self.group_extra_options_table.removeRow(row)

    def _on_group_row_moved(self, from_row: int, to_row: int) -> None:
        candidate_db = copy.deepcopy(self.db)
        if not candidate_db.move_group(from_row, to_row):
            return
        moved_group = candidate_db.groups[to_row]
        if not self._commit_db(candidate_db):
            return
        self.selected_group_name = moved_group.name
        self._refresh_all()
        self._load_group_into_form(moved_group)
        self._set_status(f"Gruppe '{moved_group.name}' auf Position {to_row + 1} verschoben")

    def _selected_group_row(self) -> int | None:
        selected_rows = self.groups_table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        return selected_rows[0].row()

    def action_move_group_up(self) -> None:
        row = self._selected_group_row()
        if row is None or row <= 0:
            return
        self._on_group_row_moved(row, row - 1)

    def action_move_group_down(self) -> None:
        row = self._selected_group_row()
        if row is None or row >= len(self.db.groups) - 1:
            return
        self._on_group_row_moved(row, row + 1)

    def action_new_group(self) -> None:
        self.selected_group_name = None
        self.groups_table.clearSelection()
        self.in_group_name.clear()
        self.in_group_desc.clear()
        self._populate_identity_combo(self.in_group_identity, None)
        self.in_group_user.clear()
        self.in_group_port.clear()
        self.group_extra_options_table.setRowCount(0)
        self.in_group_name.setFocus()

    def action_save_group(self) -> None:
        name = self.in_group_name.text().strip()
        desc = self.in_group_desc.text().strip()
        identity_data = self.in_group_identity.currentData()
        identity = str(identity_data) if identity_data else None
        user = self.in_group_user.text().strip() or None

        form_errors: list[str] = []
        port: int | None = None
        port_raw = self.in_group_port.text().strip()
        if port_raw:
            try:
                port = int(port_raw)
            except ValueError:
                form_errors.append(f"Port ist keine Zahl: {port_raw}")

        extra_options: dict[str, str] = {}
        for row in range(self.group_extra_options_table.rowCount()):
            key_item = self.group_extra_options_table.item(row, 0)
            val_item = self.group_extra_options_table.item(row, 1)
            key = key_item.text().strip() if key_item else ""
            val = val_item.text().strip() if val_item else ""
            if not key and not val:
                continue
            if not key or not val:
                form_errors.append(f"Gruppen-Option in Zeile {row + 1} ist unvollstaendig")
                continue
            if any(ch.isspace() for ch in key):
                form_errors.append(f"Gruppen-Option '{key}' darf keine Leerzeichen enthalten")
                continue
            extra_options[key] = val

        if form_errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(form_errors))
            return

        candidate_db = copy.deepcopy(self.db)
        existing = (
            candidate_db.get_group_by_name(self.selected_group_name)
            if self.selected_group_name
            else candidate_db.get_group_by_name(name)
        )
        if existing is None:
            candidate_db.groups.append(
                HostGroup(
                    name=name,
                    description=desc,
                    identity=identity,
                    user=user,
                    port=port,
                    extra_options=extra_options,
                )
            )
        else:
            old_name = existing.name
            existing.name = name
            existing.description = desc
            existing.identity = identity
            existing.user = user
            existing.port = port
            existing.extra_options = extra_options
            if old_name != name:
                for host in candidate_db.hosts:
                    host.groups = [name if g == old_name else g for g in host.groups]

        errors = candidate_db.validate()
        if errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(errors))
            return

        if not self._commit_db(candidate_db):
            return

        self.selected_group_name = name
        self._refresh_all()
        self._set_status(f"Gruppe gespeichert: {name}")

    def action_delete_group(self) -> None:
        if not self.selected_group_name:
            self._set_status("Keine Gruppe ausgewaehlt")
            return
        name = self.selected_group_name
        affected = [h.name for h in self.db.hosts if name in h.groups]
        details = (
            f"\nDie Zuordnung wird bei {len(affected)} Host(s) entfernt." if affected else ""
        )
        answer = QMessageBox.question(
            self,
            "Gruppe loeschen",
            f"Gruppe '{name}' wirklich loeschen?{details}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        candidate_db = copy.deepcopy(self.db)
        candidate_db.groups = [g for g in candidate_db.groups if g.name != name]
        for host in candidate_db.hosts:
            host.groups = [g for g in host.groups if g != name]

        if not self._commit_db(candidate_db):
            return

        self.action_new_group()
        self._refresh_all()
        self._set_status(f"Gruppe geloescht: {name}")

    # ------------------------------------------------------------------
    # Identity-Aktionen
    # ------------------------------------------------------------------
    def _on_identity_selection_changed(self) -> None:
        selected_rows = self.identities_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        item = self.identities_table.item(selected_rows[0].row(), 0)
        if item is None:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole))
        identity = self.db.get_identity_by_name(name)
        if identity is None:
            return
        self.selected_identity_name = identity.name
        self.in_id_name.setText(identity.name)
        self.in_id_file.setText(identity.identity_file)
        self.in_id_source.setText(identity.source)
        self.in_id_enabled.setChecked(identity.enabled)

    def _pick_profile_identity_file(self) -> None:
        start_dir = str(Path.home() / ".ssh")
        selected, _ = QFileDialog.getOpenFileName(self, "Key-Datei auswaehlen", start_dir)
        if selected:
            self.in_id_file.setText(selected)
            if not self.in_id_name.text().strip():
                self.in_id_name.setText(Path(selected).name)

    def action_new_identity(self) -> None:
        self.selected_identity_name = None
        self.identities_table.clearSelection()
        self.in_id_name.clear()
        self.in_id_file.clear()
        self.in_id_source.setText("manual")
        self.in_id_enabled.setChecked(True)
        self.in_id_name.setFocus()

    def action_save_identity(self) -> None:
        name = self.in_id_name.text().strip()
        identity_file = self.in_id_file.text().strip()
        source = self.in_id_source.text().strip() or "manual"
        enabled = self.in_id_enabled.isChecked()

        candidate_db = copy.deepcopy(self.db)
        existing = (
            candidate_db.get_identity_by_name(self.selected_identity_name)
            if self.selected_identity_name
            else candidate_db.get_identity_by_name(name)
        )
        if existing is None:
            candidate_db.identities.append(
                IdentityProfile(
                    name=name,
                    identity_file=identity_file,
                    source=source,
                    enabled=enabled,
                )
            )
        else:
            old_name = existing.name
            existing.name = name
            existing.identity_file = identity_file
            existing.source = source
            existing.enabled = enabled
            if old_name != name:
                for group in candidate_db.groups:
                    if group.identity == old_name:
                        group.identity = name
                for host in candidate_db.hosts:
                    if host.identity == old_name:
                        host.identity = name

        errors = candidate_db.validate()
        if errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(errors))
            return

        if not self._commit_db(candidate_db):
            return

        self.selected_identity_name = name
        self._refresh_all()
        self._set_status(f"Identity gespeichert: {name}")

    def action_toggle_identity_enabled(self) -> None:
        if not self.selected_identity_name:
            self._set_status("Keine Identity ausgewaehlt")
            return
        candidate_db = copy.deepcopy(self.db)
        identity = candidate_db.get_identity_by_name(self.selected_identity_name)
        if identity is None:
            return
        identity.enabled = not identity.enabled

        if not self._commit_db(candidate_db):
            return

        self.in_id_enabled.setChecked(identity.enabled)
        self._refresh_all()
        self._set_status(f"Identity '{identity.name}' aktiv={identity.enabled}")

    def action_delete_identity(self) -> None:
        if not self.selected_identity_name:
            self._set_status("Keine Identity ausgewaehlt")
            return
        name = self.selected_identity_name
        answer = QMessageBox.question(
            self,
            "Identity loeschen",
            f"Identity '{name}' wirklich loeschen? Referenzen in Hosts/Gruppen werden geleert.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        candidate_db = copy.deepcopy(self.db)
        candidate_db.identities = [i for i in candidate_db.identities if i.name != name]
        for group in candidate_db.groups:
            if group.identity == name:
                group.identity = None
        for host in candidate_db.hosts:
            if host.identity == name:
                host.identity = None

        if not self._commit_db(candidate_db):
            return

        self.action_new_identity()
        self._refresh_all()
        self._set_status(f"Identity geloescht: {name}")

    def action_scan_identities(self) -> None:
        discovered = discover_ssh_identities()
        candidate_db = copy.deepcopy(self.db)
        created, updated = merge_discovered_identities(candidate_db, discovered)
        errors = candidate_db.validate()
        if errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(errors))
            return
        if not self._commit_db(candidate_db):
            return

        self._refresh_all()
        self._set_status(
            f"Identity-Scan: gefunden={len(discovered)}, neu={created}, aktualisiert={updated}"
        )

    # ------------------------------------------------------------------
    # Import / Generate / Dedup / Persistenz
    # ------------------------------------------------------------------
    def _commit_db(self, candidate_db: HostDatabase) -> bool:
        try:
            save_database(candidate_db)
        except OSError as exc:
            QMessageBox.critical(self, "Speicherfehler", str(exc))
            return False
        self.db = candidate_db
        return True

    def action_import_config(self) -> None:
        start_dir = str(Path.home() / ".ssh")
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "OpenSSH-Config importieren",
            start_dir,
        )
        if not selected:
            return

        if self.db.hosts:
            answer = QMessageBox.question(
                self,
                "Import bestaetigen",
                "Der Import ersetzt die aktuelle Host-Datenbank "
                "(vorher wird automatisch ein Zeitstempel-Backup von hosts.toml erstellt). "
                "Fortfahren?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            imported_db, report = import_ssh_config(Path(selected))
        except OSError as exc:
            QMessageBox.critical(self, "Importfehler", str(exc))
            return

        errors = imported_db.validate()
        if errors:
            QMessageBox.warning(self, "Import-Validierungsfehler", "\n".join(errors))
            return

        if not self._commit_db(imported_db):
            return

        self.action_new_host()
        self._refresh_all()
        warning_text = (
            "\n\nWarnungen:\n- " + "\n- ".join(report.warnings[:10]) if report.warnings else ""
        )
        QMessageBox.information(
            self,
            "Import abgeschlossen",
            f"{report.summary()}{warning_text}",
        )
        self._set_status(f"Import ok: {report.summary()}")

    def action_generate_config(self) -> None:
        self._write_config_to(GENERATED_CONFIG_PATH)

    def action_export_config_as(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "OpenSSH-Config exportieren",
            str(GENERATED_CONFIG_PATH),
        )
        if selected:
            self._write_config_to(Path(selected))

    def _write_config_to(self, output_path: Path) -> None:
        errors = self.db.validate()
        if errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(errors))
            return
        try:
            target = write_generated_config(self.db, output=output_path)
        except OSError as exc:
            QMessageBox.critical(self, "Fehler beim Generieren", str(exc))
            return

        self._refresh_preview()
        self._set_status(f"Config generiert: {target}")

    def action_open_dedup(self) -> None:
        dialog = DuplicateReviewDialog(self.db, parent=self)
        dialog.exec()
        if dialog.changed:
            self.db = dialog.db
            selected = (
                self.db.get_by_id(self.selected_host_id) if self.selected_host_id else None
            )
            if selected is None:
                self.action_new_host()
            else:
                self._load_host_into_form(selected)
            self._refresh_all()
            self._set_status("Dubletten-Aenderungen uebernommen")
