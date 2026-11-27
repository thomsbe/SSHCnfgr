from __future__ import annotations

import copy

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..dedup import (
    DnsResolutionMap,
    DuplicateGroup,
    MergeDisposition,
    MergePlan,
    analyze_group_conflicts,
    apply_merge,
    build_merged_host,
    default_conflict_choices,
    find_duplicate_groups,
    resolve_hostnames_dns,
)
from ..model import HostDatabase, HostEntry
from ..store import save_database


class _DnsResolveWorker(QThread):
    """Fuehrt Forward- und Reverse-DNS-Lookups im Hintergrund aus, ohne die GUI zu blockieren."""

    result_ready = Signal(object)

    def __init__(self, hosts: list[HostEntry], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hosts = hosts

    def run(self) -> None:
        dns_map = resolve_hostnames_dns(self._hosts, include_ptr=True)
        self.result_ready.emit(dns_map)


def _setup_table(table: QTableWidget, headers: list[str]) -> None:
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)


class DuplicateReviewDialog(QDialog):
    """Interaktiver Qt6-Dialog zum Pruefen und Zusammenfuehren von Host-Dubletten."""

    def __init__(self, db: HostDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dubletten pruefen & zusammenfuehren")
        self.resize(1120, 700)
        self.setMinimumSize(860, 540)

        self.db: HostDatabase = copy.deepcopy(db)
        self.changed = False

        self._groups: list[DuplicateGroup] = []
        self._selected_index: int | None = None
        self._conflict_combos: dict[str, QComboBox] = {}
        self._loading_group = False
        self._dns_map: DnsResolutionMap | None = None
        self._dns_worker: _DnsResolveWorker | None = None

        self._build_ui()
        self._refresh_groups(preferred_index=0)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top_bar = QHBoxLayout()
        title = QLabel(
            "Potentielle Dubletten (gleicher HostName / aufgeloeste IP + Port + User)",
            self,
        )
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)

        self.include_inactive_cb = QCheckBox("Inaktive einschliessen", self)
        self.include_inactive_cb.toggled.connect(lambda _: self._refresh_groups(0))

        self.btn_dns_check = QPushButton("Per DNS pruefen", self)
        self.btn_dns_check.setToolTip(
            "Loest Hostnamen einmalig per DNS auf (Name -> IP + PTR-Hinweis), "
            "um versteckte Dubletten zwischen IP und Hostname zu finden."
        )
        self.btn_dns_check.clicked.connect(self.action_run_dns_check)

        self.btn_dns_reset = QPushButton("Nur Exakt", self)
        self.btn_dns_reset.setToolTip("DNS-Ergebnisse verwerfen und wieder nur exakt vergleichen")
        self.btn_dns_reset.setEnabled(False)
        self.btn_dns_reset.clicked.connect(self.action_clear_dns)

        top_bar.addWidget(title, stretch=1)
        top_bar.addWidget(self.include_inactive_cb)
        top_bar.addWidget(self.btn_dns_check)
        top_bar.addWidget(self.btn_dns_reset)
        root.addLayout(top_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Links: Liste aller Dubletten-Gruppen
        left_widget = QWidget(splitter)
        left_layout = QVBoxLayout(left_widget)

        self.groups_label = QLabel("Dubletten-Gruppen", left_widget)
        left_layout.addWidget(self.groups_label)

        self.groups_table = QTableWidget(left_widget)
        _setup_table(self.groups_table, ["Ziel", "Match", "Anzahl", "Aliase", "Konflikte"])
        self.groups_table.itemSelectionChanged.connect(self._on_group_selection_changed)
        left_layout.addWidget(self.groups_table, stretch=1)

        left_btns = QHBoxLayout()
        self.btn_next = QPushButton("Naechste", left_widget)
        self.btn_next.clicked.connect(self.action_next_group)
        self.btn_close = QPushButton("Schliessen", left_widget)
        self.btn_close.clicked.connect(self.accept)
        left_btns.addWidget(self.btn_next)
        left_btns.addStretch(1)
        left_btns.addWidget(self.btn_close)
        left_layout.addLayout(left_btns)

        # Rechts: Kandidaten, Konflikte, Vorschau und Merge-Aktion
        right_scroll = QScrollArea(splitter)
        right_scroll.setWidgetResizable(True)
        right_container = QWidget(right_scroll)
        right_layout = QVBoxLayout(right_container)

        members_box = QGroupBox("Kandidaten in ausgewaehlter Gruppe", right_container)
        self.members_box = members_box
        members_layout = QVBoxLayout(members_box)
        self.members_table = QTableWidget(members_box)
        _setup_table(
            self.members_table,
            [
                "Alias",
                "HostName",
                "DNS / IP",
                "User",
                "Port",
                "Identity",
                "Gruppen",
                "Extra",
                "Aktiv",
            ],
        )
        self.members_table.setMinimumHeight(140)
        members_layout.addWidget(self.members_table)
        right_layout.addWidget(members_box)

        merge_box = QGroupBox("Zusammenfuehren (Merge)", right_container)
        merge_layout = QVBoxLayout(merge_box)

        base_form = QFormLayout()
        self.primary_combo = QComboBox(merge_box)
        self.primary_combo.currentIndexChanged.connect(self._on_primary_changed)

        self.target_name_input = QLineEdit(merge_box)
        self.target_name_input.setPlaceholderText("Alias fuer zusammengefuehrten Host")
        self.target_name_input.textChanged.connect(self._update_preview)

        self.disposition_combo = QComboBox(merge_box)
        self.disposition_combo.addItem("Deaktivieren (enabled=false, empfohlen)", "disable")
        self.disposition_combo.addItem("Endgueltig loeschen", "delete")
        self.disposition_combo.currentIndexChanged.connect(self._update_preview)

        base_form.addRow("Basis-Eintrag behalten:", self.primary_combo)
        base_form.addRow("Ziel-Alias:", self.target_name_input)
        base_form.addRow("Uebrige Dubletten:", self.disposition_combo)
        merge_layout.addLayout(base_form)

        conflicts_box = QGroupBox("Abweichende Felder (Konflikte)", merge_box)
        self.conflicts_layout = QFormLayout(conflicts_box)
        merge_layout.addWidget(conflicts_box)

        right_layout.addWidget(merge_box)

        preview_box = QGroupBox("Vorschau", right_container)
        preview_layout = QVBoxLayout(preview_box)
        self.preview_edit = QPlainTextEdit(preview_box)
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setMaximumHeight(130)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self.preview_edit.setFont(mono)
        preview_layout.addWidget(self.preview_edit)
        right_layout.addWidget(preview_box)

        merge_btns = QHBoxLayout()
        self.btn_merge = QPushButton("Gruppe zusammenfuehren", right_container)
        self.btn_merge.setDefault(True)
        self.btn_merge.clicked.connect(self.action_merge_current)
        self.btn_skip = QPushButton("Ueberspringen", right_container)
        self.btn_skip.clicked.connect(self.action_next_group)
        merge_btns.addWidget(self.btn_merge)
        merge_btns.addWidget(self.btn_skip)
        merge_btns.addStretch(1)
        right_layout.addLayout(merge_btns)

        self.status_label = QLabel("", right_container)
        self.status_label.setWordWrap(True)
        right_layout.addWidget(self.status_label)
        right_layout.addStretch(1)

        right_scroll.setWidget(right_container)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_scroll)
        splitter.setSizes([420, 680])
        root.addWidget(splitter, stretch=1)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._dns_worker is not None and self._dns_worker.isRunning():
            try:
                self._dns_worker.result_ready.disconnect(self._on_dns_resolved)
            except RuntimeError:
                pass
        super().closeEvent(event)

    def _current_group(self) -> DuplicateGroup | None:
        if self._selected_index is None:
            return None
        if not (0 <= self._selected_index < len(self._groups)):
            return None
        return self._groups[self._selected_index]

    def _clear_conflicts_layout(self) -> None:
        self._conflict_combos.clear()
        while self.conflicts_layout.rowCount() > 0:
            self.conflicts_layout.removeRow(0)

    def action_run_dns_check(self) -> None:
        """Startet den expliziten DNS-Check im Hintergrund-Thread."""
        if self._dns_worker is not None and self._dns_worker.isRunning():
            return

        include_inactive = self.include_inactive_cb.isChecked()
        hosts = [h for h in self.db.hosts if include_inactive or h.enabled]
        if not hosts:
            self.status_label.setText("Keine Hosts zum Aufloesen vorhanden.")
            return

        self.btn_dns_check.setEnabled(False)
        self.btn_dns_check.setText("DNS laeuft…")
        self.btn_dns_reset.setEnabled(False)
        self.status_label.setText(f"Loese {len(hosts)} Host(s) per DNS auf…")

        worker = _DnsResolveWorker(copy.deepcopy(hosts), parent=self)
        worker.result_ready.connect(self._on_dns_resolved)
        worker.finished.connect(worker.deleteLater)
        self._dns_worker = worker
        worker.start()

    def _on_dns_resolved(self, dns_map: object) -> None:
        self._dns_worker = None
        self.btn_dns_check.setEnabled(True)
        self.btn_dns_check.setText("Per DNS neu pruefen")
        if isinstance(dns_map, DnsResolutionMap):
            self.apply_dns_map(dns_map)

    def apply_dns_map(self, dns_map: DnsResolutionMap) -> None:
        """Uebernimmt ein DNS-Aufloesungsergebnis und aktualisiert die Dublettenliste."""
        self._dns_map = dns_map
        self.btn_dns_reset.setEnabled(True)
        self._refresh_groups(preferred_index=0)
        dns_groups = sum(1 for g in self._groups if g.match_source == "dns")
        self.status_label.setText(
            f"DNS-Check fertig ({dns_map.summary()}) — "
            f"{len(self._groups)} Gruppe(n) gesamt, davon {dns_groups} per DNS."
        )

    def action_clear_dns(self) -> None:
        """Schaltet zurueck auf rein exakten HostName-Vergleich."""
        self._dns_map = None
        self.btn_dns_reset.setEnabled(False)
        self.btn_dns_check.setText("Per DNS pruefen")
        self._refresh_groups(preferred_index=0)
        self.status_label.setText("DNS-Ergebnisse ausgeblendet — nur exakter HostName-Vergleich.")

    def _refresh_groups(self, preferred_index: int = 0) -> None:
        include_inactive = self.include_inactive_cb.isChecked()
        self._groups = find_duplicate_groups(
            self.db,
            include_inactive=include_inactive,
            dns_map=self._dns_map,
        )
        mode_tag = " [inkl. DNS]" if self._dns_map is not None else ""
        self.groups_label.setText(f"Dubletten-Gruppen ({len(self._groups)}){mode_tag}")

        self.groups_table.blockSignals(True)
        try:
            self.groups_table.setRowCount(len(self._groups))
            for idx, group in enumerate(self._groups):
                conflicts = analyze_group_conflicts(group)
                self.groups_table.setItem(idx, 0, QTableWidgetItem(group.label))
                self.groups_table.setItem(idx, 1, QTableWidgetItem(group.match_badge))
                self.groups_table.setItem(idx, 2, QTableWidgetItem(str(len(group.hosts))))
                self.groups_table.setItem(idx, 3, QTableWidgetItem(", ".join(group.aliases)))
                self.groups_table.setItem(idx, 4, QTableWidgetItem(str(len(conflicts))))

            if self._groups:
                target_idx = min(max(preferred_index, 0), len(self._groups) - 1)
                self._selected_index = target_idx
                self.groups_table.selectRow(target_idx)
            else:
                self._selected_index = None
        finally:
            self.groups_table.blockSignals(False)

        self._load_group_details(self._current_group())
        if not self._groups and self._dns_map is None:
            self.status_label.setText(
                "Keine exakten Dubletten gefunden. Tipp: 'Per DNS pruefen' findet auch "
                "Name-vs-IP-Dubletten."
            )

    def _load_group_details(self, group: DuplicateGroup | None) -> None:
        self._loading_group = True
        try:
            self.members_table.setRowCount(0)
            self.primary_combo.clear()
            self._clear_conflicts_layout()

            if group is None:
                self.members_box.setTitle("Kandidaten in ausgewaehlter Gruppe")
                self.target_name_input.clear()
                self.btn_merge.setEnabled(False)
                self.conflicts_layout.addRow(QLabel("Keine Dubletten-Gruppe ausgewaehlt."))
                self.preview_edit.setPlainText("-")
                return

            self.btn_merge.setEnabled(True)
            badge = f" — {group.match_badge}" if group.match_source == "dns" else ""
            self.members_box.setTitle(
                f"Kandidaten fuer {group.label} ({len(group.hosts)} Eintraege{badge})"
            )

            self.members_table.setRowCount(len(group.hosts))
            for row, host in enumerate(group.hosts):
                identity_display = (
                    host.identity_file
                    or host.identity
                    or self.db.resolve_identity_file(host)
                    or ""
                )
                extra_summary = ", ".join(
                    f"{k}={v}"
                    for k, v in sorted(host.extra_options.items(), key=lambda pair: pair[0].lower())
                )
                dns_info = (
                    self._dns_map.describe_host_name(host.host_name)
                    if self._dns_map is not None
                    else ""
                )
                self.members_table.setItem(row, 0, QTableWidgetItem(host.name))
                self.members_table.setItem(row, 1, QTableWidgetItem(host.host_name))
                self.members_table.setItem(row, 2, QTableWidgetItem(dns_info))
                self.members_table.setItem(
                    row,
                    3,
                    QTableWidgetItem(host.user or f"({self.db.resolve_user(host) or '-'})"),
                )
                self.members_table.setItem(
                    row,
                    4,
                    QTableWidgetItem(
                        str(host.port)
                        if host.port is not None
                        else f"({self.db.resolve_port(host)})"
                    ),
                )
                self.members_table.setItem(row, 5, QTableWidgetItem(identity_display))
                self.members_table.setItem(row, 6, QTableWidgetItem(", ".join(host.groups)))
                self.members_table.setItem(row, 7, QTableWidgetItem(extra_summary))
                self.members_table.setItem(
                    row, 8, QTableWidgetItem("Ja" if host.enabled else "Nein")
                )

                state_label = "aktiv" if host.enabled else "inaktiv"
                self.primary_combo.addItem(f"{host.name} ({state_label})", host.id)

            default_primary = group.hosts[0]
            self.primary_combo.setCurrentIndex(0)
            self.target_name_input.setText(default_primary.name)

            conflicts = analyze_group_conflicts(group)
            defaults = default_conflict_choices(group, default_primary.id, conflicts)

            if not conflicts:
                hint = QLabel(
                    "Keine Feld-Konflikte: fehlende Felder, Gruppen, Tags und Extra-Optionen "
                    "werden automatisch vereint."
                )
                hint.setWordWrap(True)
                self.conflicts_layout.addRow(hint)
            else:
                for conflict in conflicts:
                    combo = QComboBox()
                    for opt in conflict.options:
                        combo.addItem(opt.display_label, opt.value)
                    if conflict.allow_empty:
                        combo.addItem("(leer)", None)

                    default_val = defaults.get(conflict.field)
                    idx = combo.findData(default_val)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)

                    combo.currentIndexChanged.connect(self._update_preview)
                    self._conflict_combos[conflict.field] = combo
                    self.conflicts_layout.addRow(f"{conflict.label}:", combo)
        finally:
            self._loading_group = False

        self._update_preview()

    def _on_group_selection_changed(self) -> None:
        selected = self.groups_table.selectionModel().selectedRows()
        if not selected:
            return
        idx = selected[0].row()
        if 0 <= idx < len(self._groups):
            self._selected_index = idx
            self._load_group_details(self._groups[idx])
            self.status_label.setText(f"Gruppe ausgewaehlt: {self._groups[idx].label}")

    def _on_primary_changed(self) -> None:
        if self._loading_group:
            return
        group = self._current_group()
        primary_id = self.primary_combo.currentData()
        if group is not None and primary_id:
            primary = group.get_host_by_id(str(primary_id))
            if primary is not None:
                self.target_name_input.setText(primary.name)
        self._update_preview()

    def _collect_resolved_fields(self) -> dict[str, str | None]:
        resolved: dict[str, str | None] = {}
        for field_name, combo in self._conflict_combos.items():
            value = combo.currentData()
            resolved[field_name] = str(value) if value is not None else None
        return resolved

    def _current_disposition(self) -> MergeDisposition:
        return "delete" if self.disposition_combo.currentData() == "delete" else "disable"

    def _format_preview(self, merged: HostEntry, group: DuplicateGroup) -> str:
        disposition = self._current_disposition()
        others = [h.name for h in group.hosts if h.id != merged.id]
        action_text = "werden deaktiviert" if disposition == "disable" else "werden geloescht"
        eff_user = merged.user or self.db.resolve_user(merged) or "-"
        eff_port = merged.port if merged.port is not None else self.db.resolve_port(merged)
        groups_str = ", ".join(merged.groups) if merged.groups else "-"
        tags_str = ", ".join(merged.tags) if merged.tags else "-"
        extra_str = (
            ", ".join(f"{k}={v}" for k, v in sorted(merged.extra_options.items()))
            if merged.extra_options
            else "-"
        )
        return "\n".join(
            [
                f"Host: {merged.name or '<leer>'}  ->  {eff_user}@{merged.host_name}:{eff_port}",
                f"Identity: {merged.identity or '-'} | IdentityFile: {merged.identity_file or '-'}",
                f"Gruppen: {groups_str} | Tags: {tags_str}",
                f"Extra: {extra_str}",
                f"Uebrige ({action_text}): {', '.join(others)}",
            ]
        )

    def _update_preview(self) -> None:
        if self._loading_group:
            return
        group = self._current_group()
        primary_id = self.primary_combo.currentData()
        if group is None or not primary_id:
            self.preview_edit.setPlainText("-")
            return

        target_name = self.target_name_input.text().strip()
        resolved = self._collect_resolved_fields()
        plan = MergePlan(
            group=group,
            primary_host_id=str(primary_id),
            target_name=target_name,
            resolved_fields=resolved,
            disposition=self._current_disposition(),
        )
        merged = build_merged_host(
            group=group,
            primary_host_id=str(primary_id),
            target_name=target_name,
            resolved_fields=resolved,
        )
        _, _, errors = apply_merge(self.db, plan)

        text = self._format_preview(merged, group)
        if errors:
            text += f"\n\nHinweis: {'; '.join(errors)}"
        self.preview_edit.setPlainText(text)

    def action_next_group(self) -> None:
        if not self._groups:
            self.status_label.setText("Keine weiteren Dubletten-Gruppen vorhanden.")
            return
        current = self._selected_index if self._selected_index is not None else -1
        next_idx = (current + 1) % len(self._groups)
        self._selected_index = next_idx
        self.groups_table.selectRow(next_idx)
        group = self._groups[next_idx]
        self._load_group_details(group)
        self.status_label.setText(f"Gruppe {next_idx + 1}/{len(self._groups)}: {group.label}")

    def action_merge_current(self) -> None:
        group = self._current_group()
        primary_id = self.primary_combo.currentData()
        if group is None or not primary_id:
            return

        disposition = self._current_disposition()
        plan = MergePlan(
            group=group,
            primary_host_id=str(primary_id),
            target_name=self.target_name_input.text().strip(),
            resolved_fields=self._collect_resolved_fields(),
            disposition=disposition,
        )

        candidate_db, merged, errors = apply_merge(self.db, plan)
        if errors:
            QMessageBox.warning(self, "Validierungsfehler", "\n".join(errors))
            return

        try:
            save_database(candidate_db)
        except OSError as exc:
            QMessageBox.critical(self, "Speicherfehler", str(exc))
            return

        self.db = candidate_db
        self.changed = True

        dup_count = len(group.hosts) - 1
        verb = "deaktiviert" if disposition == "disable" else "geloescht"
        current_idx = self._selected_index or 0
        self._refresh_groups(preferred_index=current_idx)
        self.status_label.setText(
            f"Zusammengefuehrt: {merged.name} ({dup_count} Dublette(n) {verb}, Backup erstellt)"
        )
