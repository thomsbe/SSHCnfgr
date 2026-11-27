from __future__ import annotations

import asyncio
import copy

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
)

from .dedup import (
    DnsResolutionMap,
    DuplicateGroup,
    FieldConflict,
    MergeDisposition,
    MergePlan,
    analyze_group_conflicts,
    apply_merge,
    build_merged_host,
    default_conflict_choices,
    find_duplicate_groups,
    resolve_hostnames_dns,
)
from .model import HostDatabase, HostEntry
from .store import save_database

EMPTY_OPTION_VALUE = "__SSHCNFGR_EMPTY__"


class DuplicateReviewScreen(Screen[HostDatabase | None]):
    """Dedizierte TUI-Ansicht zum Finden und interaktiven Zusammenfuehren von Host-Dubletten."""

    BINDINGS = [
        ("escape", "close", "Zurueck"),
        ("ctrl+m", "merge_current", "Zusammenfuehren"),
        ("ctrl+r", "run_dns_check", "DNS-Check"),
        ("n", "next_group", "Naechste"),
    ]

    def __init__(self, db: HostDatabase) -> None:
        super().__init__()
        self._db: HostDatabase = copy.deepcopy(db)
        self._changed = False
        self._include_inactive = False
        self._groups: list[DuplicateGroup] = []
        self._selected_index: int | None = None
        self._current_conflicts: list[FieldConflict] = []
        self._conflict_selects: dict[str, Select[str]] = {}
        self._loading_group = False
        self._dns_map: DnsResolutionMap | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="dedup_toolbar"):
            yield Label(
                "Potentielle Dubletten (HostName / DNS-IP + Port + User)",
                id="dedup_title",
            )
            yield Checkbox(
                "Inaktive einschliessen",
                value=False,
                id="dedup_include_inactive",
            )
            yield Button("Per DNS pruefen", id="btn_dedup_dns", variant="primary")
            yield Button("Nur Exakt", id="btn_dedup_dns_reset", disabled=True)
        with Horizontal(id="dedup_body"):
            with Vertical(id="dedup_left"):
                yield Label("Dubletten-Gruppen", id="dedup_groups_label")
                yield DataTable(id="dedup_groups_table", cursor_type="row")
                with Horizontal(id="dedup_left_actions"):
                    yield Button("Zurueck (Esc)", id="btn_dedup_close")
                    yield Button("Naechste", id="btn_dedup_next")
            with VerticalScroll(id="dedup_right"):
                yield Label("Kandidaten in ausgewaehlter Gruppe", id="dedup_members_label")
                yield DataTable(id="dedup_members_table", cursor_type="row")

                yield Label("Basis-Eintrag behalten:")
                yield Select(
                    [],
                    prompt="Keine Gruppe ausgewaehlt",
                    id="dedup_primary_select",
                    allow_blank=True,
                )

                yield Label("Ziel-Alias:")
                yield Input(
                    placeholder="Alias fuer zusammengefuehrten Host",
                    id="dedup_target_name",
                )

                yield Label("Abweichende Felder (Konflikte):", id="dedup_conflicts_label")
                yield Vertical(id="dedup_conflicts_container")

                yield Label("Uebrige Dubletten behandeln als:")
                yield Select(
                    [
                        ("Deaktivieren (enabled=false, empfohlen)", "disable"),
                        ("Endgueltig loeschen", "delete"),
                    ],
                    value="disable",
                    allow_blank=False,
                    id="dedup_disposition",
                )

                yield Label("Vorschau:")
                yield Static("", id="dedup_preview")

                with Horizontal(id="dedup_merge_actions"):
                    yield Button(
                        "Gruppe zusammenfuehren",
                        id="btn_dedup_merge",
                        variant="success",
                    )
                    yield Button("Ueberspringen", id="btn_dedup_skip")

                yield Static("", id="dedup_status")
        yield Footer()

    async def on_mount(self) -> None:
        groups_table = self.query_one("#dedup_groups_table", DataTable)
        groups_table.add_columns("Ziel", "Match", "Anzahl", "Aliase", "Konflikte")

        members_table = self.query_one("#dedup_members_table", DataTable)
        members_table.add_columns(
            "Alias",
            "HostName",
            "DNS / IP",
            "User",
            "Port",
            "Identity",
            "Groups",
            "Extra",
            "Aktiv",
        )

        await self._refresh_groups()

    def _set_status(self, message: str) -> None:
        self.query_one("#dedup_status", Static).update(message)

    def _current_group(self) -> DuplicateGroup | None:
        if self._selected_index is None:
            return None
        if not (0 <= self._selected_index < len(self._groups)):
            return None
        return self._groups[self._selected_index]

    async def _refresh_groups(self, preferred_index: int = 0) -> None:
        self._groups = find_duplicate_groups(
            self._db,
            include_inactive=self._include_inactive,
            dns_map=self._dns_map,
        )
        mode_tag = " [inkl. DNS]" if self._dns_map is not None else ""
        self.query_one("#dedup_groups_label", Label).update(
            f"Dubletten-Gruppen ({len(self._groups)}){mode_tag}"
        )

        groups_table = self.query_one("#dedup_groups_table", DataTable)
        groups_table.clear(columns=False)

        for idx, group in enumerate(self._groups):
            conflicts = analyze_group_conflicts(group)
            aliases_text = ", ".join(group.aliases)
            groups_table.add_row(
                group.label,
                group.match_badge,
                str(len(group.hosts)),
                aliases_text,
                str(len(conflicts)),
                key=str(idx),
            )

        if not self._groups:
            self._selected_index = None
            await self._load_group_details(None)
            if self._dns_map is None:
                self._set_status(
                    "Keine exakten Dubletten gefunden. Tipp: 'Per DNS pruefen' (Ctrl+R)."
                )
            return

        target_index = min(max(preferred_index, 0), len(self._groups) - 1)
        self._selected_index = target_index
        groups_table.move_cursor(row=target_index)
        await self._load_group_details(self._groups[target_index])

    async def _load_group_details(self, group: DuplicateGroup | None) -> None:
        self._loading_group = True
        try:
            members_table = self.query_one("#dedup_members_table", DataTable)
            members_table.clear(columns=False)

            primary_select = self.query_one("#dedup_primary_select", Select)
            target_name_input = self.query_one("#dedup_target_name", Input)
            conflicts_container = self.query_one("#dedup_conflicts_container", Vertical)
            merge_button = self.query_one("#btn_dedup_merge", Button)

            await conflicts_container.remove_children()
            self._conflict_selects.clear()
            self._current_conflicts = []

            if group is None:
                self.query_one("#dedup_members_label", Label).update(
                    "Kandidaten in ausgewaehlter Gruppe"
                )
                primary_select.set_options([])
                target_name_input.value = ""
                merge_button.disabled = True
                await conflicts_container.mount(
                    Static("Keine Dubletten-Gruppe ausgewaehlt.", classes="dedup-hint")
                )
                self.query_one("#dedup_preview", Static).update("-")
                return

            merge_button.disabled = False
            self.query_one("#dedup_members_label", Label).update(
                f"Kandidaten fuer {group.label} ({len(group.hosts)} Eintraege)"
            )

            for host in group.hosts:
                identity_display = (
                    host.identity_file
                    or host.identity
                    or self._db.resolve_identity_file(host)
                    or ""
                )
                extra_summary = ", ".join(
                    f"{k}={v}"
                    for k, v in sorted(host.extra_options.items(), key=lambda item: item[0].lower())
                )
                dns_info = (
                    self._dns_map.describe_host_name(host.host_name)
                    if self._dns_map is not None
                    else ""
                )
                members_table.add_row(
                    host.name,
                    host.host_name,
                    dns_info,
                    host.user or f"({self._db.resolve_user(host) or '-'})",
                    str(host.port) if host.port is not None else f"({self._db.resolve_port(host)})",
                    identity_display,
                    ",".join(host.groups),
                    extra_summary,
                    "yes" if host.enabled else "no",
                    key=host.id,
                )

            primary_options = [
                (f"{host.name} ({'aktiv' if host.enabled else 'inaktiv'})", host.id)
                for host in group.hosts
            ]
            default_primary = group.hosts[0]
            primary_select.set_options(primary_options)
            primary_select.value = default_primary.id
            target_name_input.value = default_primary.name

            conflicts = analyze_group_conflicts(group)
            self._current_conflicts = conflicts
            defaults = default_conflict_choices(group, default_primary.id, conflicts)

            if not conflicts:
                await conflicts_container.mount(
                    Static(
                        "Keine Feld-Konflikte: fehlende Felder, Gruppen, Tags und "
                        "Extra-Optionen werden automatisch vereint.",
                        classes="dedup-hint",
                    )
                )
            else:
                for conflict in conflicts:
                    options: list[tuple[str, str]] = [
                        (opt.display_label, opt.value)
                        for opt in conflict.options
                        if opt.value is not None
                    ]
                    if conflict.allow_empty:
                        options.append(("(leer)", EMPTY_OPTION_VALUE))

                    default_value = defaults.get(conflict.field)
                    initial = default_value if default_value is not None else EMPTY_OPTION_VALUE

                    select_widget: Select[str] = Select(
                        options,
                        value=initial,
                        allow_blank=False,
                    )
                    self._conflict_selects[conflict.field] = select_widget
                    await conflicts_container.mount(Label(f"{conflict.label}:"), select_widget)
        finally:
            self._loading_group = False

        self._update_preview()

    def _collect_resolved_fields(self) -> dict[str, str | None]:
        resolved: dict[str, str | None] = {}
        for field_name, select_widget in self._conflict_selects.items():
            if select_widget.is_blank() or select_widget.value == EMPTY_OPTION_VALUE:
                resolved[field_name] = None
            else:
                resolved[field_name] = str(select_widget.value)
        return resolved

    def _current_primary_id(self) -> str | None:
        primary_select = self.query_one("#dedup_primary_select", Select)
        if primary_select.is_blank():
            return None
        return str(primary_select.value)

    def _current_disposition(self) -> MergeDisposition:
        disposition_select = self.query_one("#dedup_disposition", Select)
        if disposition_select.value == "delete":
            return "delete"
        return "disable"

    def _format_host_preview(self, merged: HostEntry, group: DuplicateGroup) -> str:
        disposition = self._current_disposition()
        others = [h.name for h in group.hosts if h.id != merged.id]
        action_text = "werden deaktiviert" if disposition == "disable" else "werden geloescht"

        eff_user = merged.user or self._db.resolve_user(merged) or "-"
        eff_port = merged.port if merged.port is not None else self._db.resolve_port(merged)
        groups_str = ", ".join(merged.groups) if merged.groups else "-"
        tags_str = ", ".join(merged.tags) if merged.tags else "-"
        extra_str = (
            ", ".join(f"{k}={v}" for k, v in sorted(merged.extra_options.items()))
            if merged.extra_options
            else "-"
        )

        lines = [
            f"Host: {merged.name or '<leer>'}  ->  {eff_user}@{merged.host_name}:{eff_port}",
            f"Identity: {merged.identity or '-'} | IdentityFile: {merged.identity_file or '-'}",
            f"Groups: {groups_str} | Tags: {tags_str}",
            f"Extra: {extra_str}",
            f"Uebrige ({action_text}): {', '.join(others)}",
        ]
        return "\n".join(lines)

    def _update_preview(self) -> None:
        preview = self.query_one("#dedup_preview", Static)
        group = self._current_group()
        primary_id = self._current_primary_id()
        if group is None or primary_id is None:
            preview.update("-")
            return

        target_name = self.query_one("#dedup_target_name", Input).value.strip()
        resolved = self._collect_resolved_fields()

        plan = MergePlan(
            group=group,
            primary_host_id=primary_id,
            target_name=target_name,
            resolved_fields=resolved,
            disposition=self._current_disposition(),
        )
        merged = build_merged_host(
            group=group,
            primary_host_id=primary_id,
            target_name=target_name,
            resolved_fields=resolved,
        )
        _, _, errors = apply_merge(self._db, plan)

        text = self._format_host_preview(merged, group)
        if errors:
            text += f"\nHinweis: {'; '.join(errors)}"
        preview.update(text)

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "dedup_groups_table":
            return

        raw_key = str(getattr(event.row_key, "value", event.row_key))
        try:
            idx = int(raw_key)
        except ValueError:
            return

        if 0 <= idx < len(self._groups):
            self._selected_index = idx
            await self._load_group_details(self._groups[idx])
            self._set_status(f"Gruppe ausgewaehlt: {self._groups[idx].label}")

    async def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id != "dedup_include_inactive":
            return
        self._include_inactive = event.value
        await self._refresh_groups(preferred_index=0)

    def on_select_changed(self, event: Select.Changed) -> None:
        if self._loading_group:
            return

        group = self._current_group()
        if event.select.id == "dedup_primary_select" and group is not None:
            primary_id = self._current_primary_id()
            if primary_id:
                primary = group.get_host_by_id(primary_id)
                if primary is not None:
                    self.query_one("#dedup_target_name", Input).value = primary.name

        self._update_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._loading_group:
            return
        if event.input.id == "dedup_target_name":
            self._update_preview()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn_dedup_close":
            self.action_close()
        elif button_id in ("btn_dedup_next", "btn_dedup_skip"):
            await self.action_next_group()
        elif button_id == "btn_dedup_merge":
            await self.action_merge_current()
        elif button_id == "btn_dedup_dns":
            await self.action_run_dns_check()
        elif button_id == "btn_dedup_dns_reset":
            await self.action_clear_dns()

    async def action_run_dns_check(self) -> None:
        """Loest Hostnamen explizit auf Nutzeraktion per DNS auf (non-blocking)."""
        hosts = [h for h in self._db.hosts if self._include_inactive or h.enabled]
        if not hosts:
            self._set_status("Keine Hosts zum Aufloesen vorhanden.")
            return

        dns_btn = self.query_one("#btn_dedup_dns", Button)
        reset_btn = self.query_one("#btn_dedup_dns_reset", Button)
        dns_btn.disabled = True
        self._set_status(f"Loese {len(hosts)} Host(s) per DNS auf…")
        try:
            dns_map = await asyncio.to_thread(resolve_hostnames_dns, copy.deepcopy(hosts))
        finally:
            dns_btn.disabled = False

        self._dns_map = dns_map
        reset_btn.disabled = False
        await self._refresh_groups(preferred_index=0)
        dns_groups = sum(1 for g in self._groups if g.match_source == "dns")
        self._set_status(
            f"DNS-Check fertig ({dns_map.summary()}) — "
            f"{len(self._groups)} Gruppe(n) gesamt, davon {dns_groups} per DNS."
        )

    async def action_clear_dns(self) -> None:
        self._dns_map = None
        self.query_one("#btn_dedup_dns_reset", Button).disabled = True
        await self._refresh_groups(preferred_index=0)
        self._set_status("DNS-Ergebnisse ausgeblendet — nur exakter HostName-Vergleich.")

    def action_close(self) -> None:
        self.dismiss(self._db if self._changed else None)

    async def action_next_group(self) -> None:
        if not self._groups:
            self._set_status("Keine weiteren Dubletten-Gruppen vorhanden.")
            return

        current = self._selected_index if self._selected_index is not None else -1
        next_idx = (current + 1) % len(self._groups)
        self._selected_index = next_idx
        self.query_one("#dedup_groups_table", DataTable).move_cursor(row=next_idx)
        group = self._groups[next_idx]
        await self._load_group_details(group)
        self._set_status(f"Gruppe {next_idx + 1}/{len(self._groups)}: {group.label}")

    async def action_merge_current(self) -> None:
        group = self._current_group()
        primary_id = self._current_primary_id()
        if group is None or primary_id is None:
            self._set_status("Keine Dubletten-Gruppe ausgewaehlt.")
            return

        target_name = self.query_one("#dedup_target_name", Input).value.strip()
        disposition = self._current_disposition()
        plan = MergePlan(
            group=group,
            primary_host_id=primary_id,
            target_name=target_name,
            resolved_fields=self._collect_resolved_fields(),
            disposition=disposition,
        )

        candidate_db, merged, errors = apply_merge(self._db, plan)
        if errors:
            self._set_status(f"Fehler: {'; '.join(errors)}")
            return

        try:
            save_database(candidate_db)
        except OSError as exc:
            self._set_status(f"Speicherfehler: {exc}")
            return

        self._db = candidate_db
        self._changed = True

        duplicate_count = len(group.hosts) - 1
        verb = "deaktiviert" if disposition == "disable" else "geloescht"
        current_idx = self._selected_index or 0
        await self._refresh_groups(preferred_index=current_idx)
        self._set_status(
            f"Zusammengefuehrt: {merged.name} ({duplicate_count} Dublette(n) {verb}, "
            f"Backup erstellt)"
        )
