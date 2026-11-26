from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


def get_option_ci(options: dict[str, str], key: str) -> str | None:
    """Liest eine OpenSSH-Direktive case-insensitive aus einem Options-Dict."""
    if key in options:
        return options[key]
    key_lower = key.lower()
    for existing_key, value in options.items():
        if existing_key.lower() == key_lower:
            return value
    return None


@dataclass(slots=True)
class HostGroup:
    name: str
    description: str = ""
    identity: str | None = None
    user: str | None = None
    port: int | None = None
    extra_options: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name:
            errors.append("group.name darf nicht leer sein")
        if any(ch.isspace() for ch in self.name):
            errors.append("group.name darf keine Leerzeichen enthalten")
        if self.identity is not None and any(ch.isspace() for ch in self.identity):
            errors.append("group.identity darf keine Leerzeichen enthalten")
        if self.port is not None and not (1 <= self.port <= 65535):
            errors.append("group.port muss zwischen 1 und 65535 liegen")
        for key, value in self.extra_options.items():
            if not key or any(ch.isspace() for ch in key):
                errors.append(f"group.extra_options Schluessel ungueltig: '{key}'")
            if not value:
                errors.append(f"group.extra_options Wert fuer '{key}' darf nicht leer sein")
        return errors

    def has_ssh_defaults(self, db: HostDatabase) -> bool:
        """Prueft, ob diese Gruppe wirksame SSH-Defaults fuer einen Match-Block hat."""
        if self.user or self.port is not None or self.extra_options:
            return True
        if self.identity:
            identity = db.get_identity_by_name(self.identity)
            if identity and identity.enabled:
                return True
        return False


@dataclass(slots=True)
class IdentityProfile:
    name: str
    identity_file: str
    source: str = "manual"
    public_key_file: str | None = None
    public_key_preview: str | None = None
    enabled: bool = True

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name:
            errors.append("identity.name darf nicht leer sein")
        if " " in self.name:
            errors.append("identity.name darf keine Leerzeichen enthalten")
        if not self.identity_file:
            errors.append("identity.identity_file darf nicht leer sein")
        return errors


@dataclass(slots=True)
class HostEntry:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    enabled: bool = True
    host_name: str = ""
    user: str | None = None
    port: int | None = None
    identity: str | None = None
    identity_file: str | None = None
    groups: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    extra_options: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []

        if not self.name:
            errors.append("name darf nicht leer sein")
        if " " in self.name:
            errors.append("name darf keine Leerzeichen enthalten")
        if not self.host_name:
            errors.append("host_name darf nicht leer sein")
        if self.port is not None and not (1 <= self.port <= 65535):
            errors.append("port muss zwischen 1 und 65535 liegen")
        if self.identity is not None and " " in self.identity:
            errors.append("identity darf keine Leerzeichen enthalten")
        if self.identity_file is not None and not isinstance(self.identity_file, str):
            errors.append("identity_file muss ein String sein")
        if any((not group) or (" " in group) for group in self.groups):
            errors.append("groups duerfen keine leeren Werte oder Leerzeichen enthalten")

        return errors


@dataclass(slots=True)
class HostDatabase:
    groups: list[HostGroup] = field(default_factory=list)
    identities: list[IdentityProfile] = field(default_factory=list)
    global_options: dict[str, str] = field(default_factory=dict)
    hosts: list[HostEntry] = field(default_factory=list)
    ui: dict[str, str | bool] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        seen_names: set[str] = set()
        seen_groups: set[str] = set()
        seen_identities: set[str] = set()

        for identity in self.identities:
            identity_errors = identity.validate()
            for err in identity_errors:
                errors.append(f"identity {identity.name or '<leer>'}: {err}")
            if identity.name in seen_identities:
                errors.append(f"identity doppelt vorhanden: {identity.name}")
            seen_identities.add(identity.name)

        for group in self.groups:
            group_errors = group.validate()
            for err in group_errors:
                errors.append(f"group {group.name or '<leer>'}: {err}")
            if group.name in seen_groups:
                errors.append(f"group doppelt vorhanden: {group.name}")
            seen_groups.add(group.name)
            if group.identity and group.identity not in seen_identities:
                errors.append(
                    f"group {group.name}: referenziert unbekannte identity '{group.identity}'"
                )

        for host in self.hosts:
            host_errors = host.validate()
            for err in host_errors:
                errors.append(f"{host.name or '<leer>'}: {err}")

            if host.name in seen_names:
                errors.append(f"name doppelt vorhanden: {host.name}")
            seen_names.add(host.name)

            if host.identity and host.identity not in seen_identities:
                errors.append(
                    f"{host.name or '<leer>'}: referenziert unbekannte identity '{host.identity}'"
                )

            for group_name in host.groups:
                if group_name not in seen_groups:
                    errors.append(
                        f"{host.name or '<leer>'}: referenziert unbekannte group '{group_name}'"
                    )

        return errors

    def get_by_id(self, host_id: str) -> HostEntry | None:
        for host in self.hosts:
            if host.id == host_id:
                return host
        return None

    def sorted_hosts(self) -> list[HostEntry]:
        return sorted(self.hosts, key=lambda h: h.name.lower())

    def sorted_groups(self) -> list[HostGroup]:
        return sorted(self.groups, key=lambda g: g.name.lower())

    def ordered_groups(self) -> list[HostGroup]:
        """Liefert die Gruppen in der vom Nutzer festgelegten Reihenfolge."""
        return list(self.groups)

    def move_group(self, from_index: int, to_index: int) -> bool:
        """Verschiebt eine Gruppe innerhalb von self.groups (z. B. per Drag & Drop)."""
        count = len(self.groups)
        if not (0 <= from_index < count) or not (0 <= to_index < count):
            return False
        if from_index == to_index:
            return False
        group = self.groups.pop(from_index)
        self.groups.insert(to_index, group)
        return True

    def grouped_hosts(
        self, *, enabled_only: bool = False
    ) -> list[tuple[HostGroup | None, list[HostEntry]]]:
        """Gruppiert Hosts nach ihrer ersten Gruppe in der konfigurierten Gruppen-Reihenfolge.

        Innerhalb jeder Gruppe wird alphabetisch nach Alias sortiert; Hosts ohne Gruppe
        (oder mit unbekannter erster Gruppe) erscheinen am Ende.
        """
        candidates = [h for h in self.hosts if (not enabled_only or h.enabled)]
        by_group: dict[str, list[HostEntry]] = {group.name: [] for group in self.groups}
        ungrouped: list[HostEntry] = []

        for host in candidates:
            primary_group = host.groups[0] if host.groups else None
            if primary_group and primary_group in by_group:
                by_group[primary_group].append(host)
            else:
                ungrouped.append(host)

        sections: list[tuple[HostGroup | None, list[HostEntry]]] = []
        for group in self.groups:
            members = sorted(by_group[group.name], key=lambda h: h.name.lower())
            if members:
                sections.append((group, members))

        if ungrouped:
            sections.append((None, sorted(ungrouped, key=lambda h: h.name.lower())))

        return sections

    def ordered_hosts_by_group(self, *, enabled_only: bool = False) -> list[HostEntry]:
        """Flache Hostliste in Gruppen-Reihenfolge (nach erster Gruppe, dann Alias)."""
        result: list[HostEntry] = []
        for _, members in self.grouped_hosts(enabled_only=enabled_only):
            result.extend(members)
        return result

    def sorted_identities(self) -> list[IdentityProfile]:
        return sorted(self.identities, key=lambda i: i.name.lower())

    def get_group_by_name(self, group_name: str) -> HostGroup | None:
        for group in self.groups:
            if group.name == group_name:
                return group
        return None

    def get_identity_by_name(self, identity_name: str) -> IdentityProfile | None:
        for identity in self.identities:
            if identity.name == identity_name:
                return identity
        return None

    def resolve_identity_file(self, host: HostEntry) -> str | None:
        # Prioritaet: expliziter Host-Pfad > Host-Identity-Profil > Gruppen-Identity.
        if host.identity_file:
            return host.identity_file

        if host.identity:
            identity = self.get_identity_by_name(host.identity)
            if identity and identity.enabled:
                return identity.identity_file

        for group_name in host.groups:
            group = self.get_group_by_name(group_name)
            if not group or not group.identity:
                continue
            identity = self.get_identity_by_name(group.identity)
            if identity and identity.enabled:
                return identity.identity_file

        global_identity_file = get_option_ci(self.global_options, "IdentityFile")
        if global_identity_file:
            return global_identity_file

        return None

    def resolve_identity_agent(self, host: HostEntry) -> str | None:
        host_agent = get_option_ci(host.extra_options, "IdentityAgent")
        if host_agent is not None:
            return host_agent
        for group_name in host.groups:
            group = self.get_group_by_name(group_name)
            if group:
                group_agent = get_option_ci(group.extra_options, "IdentityAgent")
                if group_agent is not None:
                    return group_agent
        return get_option_ci(self.global_options, "IdentityAgent")

    def resolve_user(self, host: HostEntry) -> str | None:
        if host.user:
            return host.user
        for group_name in host.groups:
            group = self.get_group_by_name(group_name)
            if group and group.user:
                return group.user
        global_user = get_option_ci(self.global_options, "User")
        if global_user:
            return global_user
        return None

    def resolve_port(self, host: HostEntry) -> int:
        if host.port is not None:
            return host.port
        for group_name in host.groups:
            group = self.get_group_by_name(group_name)
            if group and group.port is not None:
                return group.port
        global_port = get_option_ci(self.global_options, "Port")
        if global_port:
            try:
                return int(global_port)
            except ValueError:
                pass
        return 22

    def ensure_groups(self, group_names: list[str]) -> None:
        existing = {group.name for group in self.groups}
        for group_name in group_names:
            if group_name and group_name not in existing:
                self.groups.append(HostGroup(name=group_name))
                existing.add(group_name)

    def ensure_identity(self, profile: IdentityProfile) -> None:
        if self.get_identity_by_name(profile.name) is None:
            self.identities.append(profile)
