from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(slots=True)
class HostGroup:
    name: str
    description: str = ""
    identity: str | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name:
            errors.append("group.name darf nicht leer sein")
        if " " in self.name:
            errors.append("group.name darf keine Leerzeichen enthalten")
        if self.identity is not None and " " in self.identity:
            errors.append("group.identity darf keine Leerzeichen enthalten")
        return errors


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

        global_identity_file = self.global_options.get("IdentityFile")
        if global_identity_file:
            return global_identity_file

        return None

    def resolve_identity_agent(self, host: HostEntry) -> str | None:
        if "IdentityAgent" in host.extra_options:
            return host.extra_options["IdentityAgent"]
        return self.global_options.get("IdentityAgent")

    def resolve_port(self, host: HostEntry) -> int:
        if host.port is not None:
            return host.port
        global_port = self.global_options.get("Port")
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
