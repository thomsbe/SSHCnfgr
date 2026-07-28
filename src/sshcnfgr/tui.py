from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Input, Label, Static

from .generator import write_generated_config
from .identities import discover_ssh_identities, merge_discovered_identities
from .model import HostDatabase, HostEntry
from .settings import load_ui_theme, save_ui_theme
from .store import load_database, save_database


class SSHCnfgrApp(App[None]):
    """Textual-App zur Verwaltung von SSH-Hosts aus einer TOML-Datenbasis.

    Die App haelt einen In-Memory-Stand (self.db), zeigt diesen in der Tabelle an
    und synchronisiert ueber Buttons/Hotkeys in die Datei.
    """

    CSS_PATH = "tui.tcss"
    TITLE = "SSHCnfgr"
    SUB_TITLE = "SSH-Hosts mit TOML verwalten"

    # Keybindings werden automatisch im Footer angezeigt und auf action_* gemappt.
    BINDINGS = [
        ("ctrl+s", "save", "Speichern"),
        ("ctrl+g", "generate", "Generieren"),
        ("ctrl+n", "new_host", "Neu"),
        ("ctrl+d", "delete_host", "Loeschen"),
        ("ctrl+t", "toggle_theme", "Thema"),
        ("q", "quit", "Beenden"),
    ]

    def __init__(self) -> None:
        super().__init__()
        # In-Memory-DB wird beim Mount aus TOML geladen.
        self.db = HostDatabase()
        # Referenz auf aktuell ausgewaehlten Host (ID aus dem Datenmodell).
        self.selected_host_id: str | None = None
        # Name der in der Identity-Tabelle selektierten Identity.
        self.selected_identity_name: str | None = None

    def compose(self) -> ComposeResult:
        """Deklariert das UI-Layout.

        Links: Host-Liste + Listenaktionen.
        Rechts: Detailformular + Aktionen fuer Speichern/Generieren.
        """
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Label("Hosts")
                yield DataTable(id="hosts_table", cursor_type="row")
                with Horizontal(id="list_actions"):
                    yield Button("Neu", id="btn_new", variant="primary")
                    yield Button("Loeschen", id="btn_delete", variant="error")
                    yield Button("Toggle Aktiv", id="btn_toggle")
                yield Label("Identities")
                yield DataTable(id="identities_table", cursor_type="row")
                with Horizontal(id="identity_actions"):
                    yield Button("Scan ~/.ssh", id="btn_scan_identities")
                    yield Button("Use Selected", id="btn_use_identity")
                    yield Button("Toggle Enabled", id="btn_toggle_identity")
            with Vertical(id="right"):
                yield Label("Host Details")
                yield Input(placeholder="Alias (Host)", id="name")
                yield Input(placeholder="HostName", id="host_name")
                yield Input(placeholder="User", id="user")
                yield Input(placeholder="Port", id="port")
                yield Input(placeholder="Identity Profile (Name)", id="identity")
                yield Input(placeholder="IdentityFile", id="identity_file")
                yield Input(placeholder="Groups (csv), z. B. prod,db", id="groups")
                yield Checkbox("Aktiv", id="enabled", value=True)
                with Horizontal(id="detail_actions"):
                    yield Button("Speichern", id="btn_save", variant="success")
                    yield Button("Generate", id="btn_generate", variant="warning")
                yield Label("Gruppen-Identity")
                yield Input(placeholder="Group Name", id="group_identity_target")
                with Horizontal(id="group_identity_actions"):
                    yield Button("Assign Selected Identity to Group", id="btn_set_group_identity")
                yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        """Lifecycle-Hook nach dem Aufbau des Widget-Baums.

        Hier laden wir Daten aus der TOML-Datei und initialisieren die Tabelle.
        """
        # Dark/Light wird aus app.toml gelesen und auf die App angewandt.
        self.dark = load_ui_theme()

        self.db = load_database()
        hosts_table = self.query_one("#hosts_table", DataTable)
        hosts_table.add_columns("Host", "HostName", "User", "Port", "Identity", "Aktiv")
        identities_table = self.query_one("#identities_table", DataTable)
        identities_table.add_columns("Name", "IdentityFile", "Public", "Source", "Enabled")
        self._refresh_table()
        self._refresh_identities_table()
        self._set_status(f"Bereit | Theme: {'Dunkel' if self.dark else 'Hell'}")

    def _set_status(self, message: str) -> None:
        """Schreibt eine kurze Rueckmeldung in die Statuszeile."""
        self.query_one("#status", Static).update(message)

    def _refresh_table(self) -> None:
        """Rendert die aktuelle In-Memory-DB in die DataTable.

        Die Row-Key wird auf host.id gesetzt, damit die Auswahl spaeter eindeutig
        zurueck auf das Objekt im Modell gemappt werden kann.
        """
        table = self.query_one("#hosts_table", DataTable)
        table.clear(columns=False)

        for host in self.db.sorted_hosts():
            identity_cell = self._identity_table_cell(host)
            port_cell = self._port_table_cell(host)
            table.add_row(
                host.name,
                host.host_name,
                host.user or "",
                port_cell,
                identity_cell,
                "yes" if host.enabled else "no",
                key=host.id,
            )

    def _identity_table_cell(self, host: HostEntry) -> Text:
        """Gibt den Identity-Wert fuer die Tabelle zurueck.

        Ist der Wert indirekt (z. B. via Host *), wird er gedimmt angezeigt.
        """
        if host.identity_file:
            return Text(host.identity_file)
        if host.identity:
            return Text(host.identity)

        resolved = self.db.resolve_identity_file(host)
        if resolved:
            return Text(resolved, style="dim")

        identity_agent = self.db.resolve_identity_agent(host)
        if identity_agent:
            return Text(f"agent:{identity_agent}", style="dim")
        return Text("")

    def _port_table_cell(self, host: HostEntry) -> Text:
        """Zeigt Port explizit oder effektiv (Default 22) an.

        Effektive, aber nicht explizit gesetzte Werte werden gedimmt angezeigt.
        """
        if host.port is not None:
            return Text(str(host.port))
        return Text(str(self.db.resolve_port(host)), style="dim")

    def _refresh_identities_table(self) -> None:
        table = self.query_one("#identities_table", DataTable)
        table.clear(columns=False)

        for identity in self.db.sorted_identities():
            table.add_row(
                identity.name,
                identity.identity_file,
                identity.public_key_preview or "",
                identity.source,
                "yes" if identity.enabled else "no",
                key=identity.name,
            )

    def _get_selected_host(self) -> HostEntry | None:
        """Liefert den aktuell ausgewaehlten Host oder None."""
        if not self.selected_host_id:
            return None
        return self.db.get_by_id(self.selected_host_id)

    def _load_selected_into_form(self, host: HostEntry) -> None:
        """Spiegelt ein Host-Objekt in die Formularfelder."""
        self.query_one("#name", Input).value = host.name
        self.query_one("#host_name", Input).value = host.host_name
        self.query_one("#user", Input).value = host.user or ""
        self.query_one("#port", Input).value = str(host.port or "")
        self.query_one("#identity", Input).value = host.identity or ""
        self.query_one("#identity_file", Input).value = host.identity_file or ""
        self.query_one("#groups", Input).value = ",".join(host.groups)
        self.query_one("#enabled", Checkbox).value = host.enabled

    def _read_form(self) -> tuple[HostEntry, list[str]]:
        """Liest UI-Felder ein und schreibt sie in ein Host-Objekt.

        Wenn ein Host selektiert ist, wird dieses Objekt direkt aktualisiert.
        Sonst wird ein neues HostEntry erstellt.
        """
        selected = self._get_selected_host()
        host = selected if selected is not None else HostEntry()

        host.name = self.query_one("#name", Input).value.strip()
        host.host_name = self.query_one("#host_name", Input).value.strip()
        host.user = self.query_one("#user", Input).value.strip() or None

        port_raw = self.query_one("#port", Input).value.strip()
        if port_raw:
            try:
                host.port = int(port_raw)
            except ValueError:
                # Ungueltige Eingabe fuehrt zu None; validate() meldet den Fehler.
                host.port = None
        else:
            host.port = None

        host.identity = self.query_one("#identity", Input).value.strip() or None
        host.identity_file = self.query_one("#identity_file", Input).value.strip() or None
        groups_raw = self.query_one("#groups", Input).value.strip()
        host.groups = [item.strip() for item in groups_raw.split(",") if item.strip()]
        host.enabled = self.query_one("#enabled", Checkbox).value

        return host, host.validate()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Event-Handler: Klick/Enter auf eine Tabellenzeile.

        Holt die Row-Key-ID aus dem Event, sucht das Modellobjekt und fuellt das
        Detailformular auf der rechten Seite.
        """
        table_id = event.data_table.id
        row_key = event.row_key

        if table_id == "hosts_table":
            host_id = str(getattr(row_key, "value", row_key))
            host = self.db.get_by_id(host_id)
            if host is None:
                return
            self.selected_host_id = host.id
            self._load_selected_into_form(host)
            self._set_status(f"Ausgewaehlt: {host.name}")
            return

        if table_id == "identities_table":
            identity_name = str(getattr(row_key, "value", row_key))
            self.selected_identity_name = identity_name
            self._set_status(f"Identity ausgewaehlt: {identity_name}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Zentraler Dispatcher fuer alle Button-Klicks."""
        if event.button.id == "btn_new":
            self.action_new_host()
        elif event.button.id == "btn_delete":
            self.action_delete_host()
        elif event.button.id == "btn_toggle":
            host = self._get_selected_host()
            if host is None:
                self._set_status("Kein Host ausgewaehlt")
                return
            host.enabled = not host.enabled
            self._refresh_table()
            self._set_status(f"Host {host.name} aktiv={host.enabled}")
        elif event.button.id == "btn_save":
            self.action_save()
        elif event.button.id == "btn_generate":
            self.action_generate()
        elif event.button.id == "btn_scan_identities":
            self.action_scan_identities()
        elif event.button.id == "btn_use_identity":
            self.action_use_selected_identity()
        elif event.button.id == "btn_toggle_identity":
            self.action_toggle_identity_enabled()
        elif event.button.id == "btn_set_group_identity":
            self.action_set_group_identity()

    def action_new_host(self) -> None:
        """Setzt das Formular auf 'neuer Datensatz'."""
        self.selected_host_id = None
        self.query_one("#name", Input).value = ""
        self.query_one("#host_name", Input).value = ""
        self.query_one("#user", Input).value = ""
        self.query_one("#port", Input).value = ""
        self.query_one("#identity", Input).value = ""
        self.query_one("#identity_file", Input).value = ""
        self.query_one("#groups", Input).value = ""
        self.query_one("#enabled", Checkbox).value = True
        self._set_status("Neuer Host: Felder ausfuellen und Speichern")

    def action_delete_host(self) -> None:
        """Loescht den selektierten Host direkt aus DB und Datei."""
        host = self._get_selected_host()
        if host is None:
            self._set_status("Kein Host ausgewaehlt")
            return

        self.db.hosts = [h for h in self.db.hosts if h.id != host.id]
        self.selected_host_id = None
        self._refresh_table()
        save_database(self.db)
        self._set_status(f"Host geloescht: {host.name}")

    def action_save(self) -> None:
        """Validiert Formular/DB und speichert den Zustand nach TOML."""
        host, errors = self._read_form()
        if errors:
            self._set_status("; ".join(errors))
            return

        if self.selected_host_id is None:
            self.db.hosts.append(host)
            self.selected_host_id = host.id

        self.db.ensure_groups(host.groups)

        db_errors = self.db.validate()
        if db_errors:
            self._set_status("; ".join(db_errors))
            return

        save_database(self.db)
        self._refresh_table()
        self._refresh_identities_table()
        self._set_status(f"Gespeichert: {host.name}")

    def action_generate(self) -> None:
        """Erzeugt aus der aktuellen DB die OpenSSH-Ausgabedatei."""
        target = write_generated_config(self.db)
        self._set_status(f"Generiert: {target}")

    def action_toggle_theme(self) -> None:
        """Schaltet zwischen Hell/Dunkel und speichert die Auswahl dauerhaft."""
        self.dark = not self.dark
        save_ui_theme(self.dark)
        self._set_status(f"Theme gespeichert: {'Dunkel' if self.dark else 'Hell'}")

    def action_scan_identities(self) -> None:
        """Liest Keys aus ~/.ssh ein und merged sie in die Datenbank."""
        discovered = discover_ssh_identities()
        created, updated = merge_discovered_identities(self.db, discovered)

        db_errors = self.db.validate()
        if db_errors:
            self._set_status("; ".join(db_errors))
            return

        save_database(self.db)
        self._refresh_identities_table()
        self._set_status(
            f"Identity-Scan: gefunden={len(discovered)} neu={created} aktualisiert={updated}"
        )

    def action_use_selected_identity(self) -> None:
        """Uebernimmt die gewaehlte Identity in das Host-Formular."""
        if not self.selected_identity_name:
            self._set_status("Keine Identity ausgewaehlt")
            return
        self.query_one("#identity", Input).value = self.selected_identity_name
        self._set_status(f"Identity gesetzt im Formular: {self.selected_identity_name}")

    def action_toggle_identity_enabled(self) -> None:
        """Aktiviert/deaktiviert die selektierte Identity."""
        if not self.selected_identity_name:
            self._set_status("Keine Identity ausgewaehlt")
            return

        identity = self.db.get_identity_by_name(self.selected_identity_name)
        if identity is None:
            self._set_status("Identity nicht gefunden")
            return

        identity.enabled = not identity.enabled
        save_database(self.db)
        self._refresh_identities_table()
        self._set_status(f"Identity {identity.name} enabled={identity.enabled}")

    def action_set_group_identity(self) -> None:
        """Weist die selektierte Identity einer Gruppe als Default zu."""
        if not self.selected_identity_name:
            self._set_status("Keine Identity ausgewaehlt")
            return

        group_name = self.query_one("#group_identity_target", Input).value.strip()
        if not group_name:
            self._set_status("Bitte Group Name eintragen")
            return

        self.db.ensure_groups([group_name])
        group = self.db.get_group_by_name(group_name)
        if group is None:
            self._set_status("Gruppe konnte nicht erstellt werden")
            return

        group.identity = self.selected_identity_name

        db_errors = self.db.validate()
        if db_errors:
            self._set_status("; ".join(db_errors))
            return

        save_database(self.db)
        self._set_status(f"Group {group.name} -> Identity {self.selected_identity_name}")


def run_tui() -> None:
    """Startpunkt fuer CLI-Command 'sshcnfgr tui'."""
    SSHCnfgrApp().run()
