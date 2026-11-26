from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Literal

from .model import HostDatabase, HostEntry

MergeDisposition = Literal["disable", "delete"]


@dataclass(slots=True)
class ConflictOption:
    """Ein moeglicher Feldwert innerhalb eines Dubletten-Konflikts."""

    value: str | None
    sources: list[str] = field(default_factory=list)

    @property
    def display_label(self) -> str:
        value_text = self.value if self.value is not None else "(leer)"
        if self.sources:
            return f"{value_text}  [{', '.join(self.sources)}]"
        return value_text


@dataclass(slots=True)
class FieldConflict:
    """Beschreibt ein Feld mit widerspruechlichen Werten in einer Dubletten-Gruppe."""

    field: str
    label: str
    options: list[ConflictOption] = field(default_factory=list)
    allow_empty: bool = True


@dataclass(slots=True)
class DuplicateGroup:
    """Gruppe von Hosts mit identischem Ziel (HostName + effektiver Port + effektiver User)."""

    host_name: str
    port: int
    user: str
    hosts: list[HostEntry] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, int, str]:
        return (self.host_name, self.port, self.user)

    @property
    def label(self) -> str:
        if self.user:
            return f"{self.user}@{self.host_name}:{self.port}"
        return f"{self.host_name}:{self.port}"

    @property
    def aliases(self) -> list[str]:
        return [host.name for host in self.hosts]

    def get_host_by_id(self, host_id: str) -> HostEntry | None:
        for host in self.hosts:
            if host.id == host_id:
                return host
        return None


@dataclass(slots=True)
class MergePlan:
    """Nutzerentscheidungen zum Zusammenfuehren einer Dubletten-Gruppe."""

    group: DuplicateGroup
    primary_host_id: str
    target_name: str
    resolved_fields: dict[str, str | None] = field(default_factory=dict)
    disposition: MergeDisposition = "disable"


def find_duplicate_groups(
    db: HostDatabase, *, include_inactive: bool = False
) -> list[DuplicateGroup]:
    """Findet potentielle Dubletten mit gleichem Ziel (HostName, Port, User)."""
    buckets: dict[tuple[str, int, str], list[HostEntry]] = {}

    for host in db.sorted_hosts():
        if not include_inactive and not host.enabled:
            continue

        normalized_host = host.host_name.strip().lower()
        if not normalized_host:
            continue

        effective_port = db.resolve_port(host)
        effective_user = (db.resolve_user(host) or "").strip()
        key = (normalized_host, effective_port, effective_user)
        buckets.setdefault(key, []).append(host)

    groups: list[DuplicateGroup] = []
    for (host_name, port, user), members in sorted(buckets.items()):
        if len(members) >= 2:
            groups.append(
                DuplicateGroup(
                    host_name=host_name,
                    port=port,
                    user=user,
                    hosts=members,
                )
            )

    return groups


def _collect_distinct_values(
    hosts: list[HostEntry],
    extractor: list[tuple[str, str | None]],
) -> list[ConflictOption]:
    """Sammelt eindeutige nicht-leere Werte inkl. Quell-Aliase in stabiler Reihenfolge."""
    by_value: dict[str, list[str]] = {}
    for alias, value in extractor:
        if value is None:
            continue
        cleaned = value.strip()
        if not cleaned:
            continue
        by_value.setdefault(cleaned, []).append(alias)

    return [ConflictOption(value=val, sources=sources) for val, sources in by_value.items()]


def _collect_extra_key_map(hosts: list[HostEntry]) -> dict[str, str]:
    """Erstellt ein Mapping lowercase-Key -> kanonischer Key ueber alle Hosts."""
    canonical: dict[str, str] = {}
    for host in hosts:
        for key in sorted(host.extra_options.keys(), key=lambda item: item.lower()):
            key_lower = key.lower()
            if key_lower not in canonical:
                canonical[key_lower] = key
    return canonical


def _get_extra_value_ci(host: HostEntry, key_lower: str) -> str | None:
    for key, value in host.extra_options.items():
        if key.lower() == key_lower:
            return value
    return None


def analyze_group_conflicts(group: DuplicateGroup) -> list[FieldConflict]:
    """Ermittelt alle Felder innerhalb einer Gruppe mit mehr als einem nicht-leeren Wert."""
    conflicts: list[FieldConflict] = []

    host_name_options = _collect_distinct_values(
        group.hosts,
        [(h.name, h.host_name) for h in group.hosts],
    )
    if len(host_name_options) >= 2:
        conflicts.append(
            FieldConflict(
                field="host_name",
                label="HostName (Schreibweise)",
                options=host_name_options,
                allow_empty=False,
            )
        )

    identity_options = _collect_distinct_values(
        group.hosts,
        [(h.name, h.identity) for h in group.hosts],
    )
    if len(identity_options) >= 2:
        conflicts.append(
            FieldConflict(
                field="identity",
                label="Identity Profile",
                options=identity_options,
                allow_empty=True,
            )
        )

    identity_file_options = _collect_distinct_values(
        group.hosts,
        [(h.name, h.identity_file) for h in group.hosts],
    )
    if len(identity_file_options) >= 2:
        conflicts.append(
            FieldConflict(
                field="identity_file",
                label="IdentityFile",
                options=identity_file_options,
                allow_empty=True,
            )
        )

    canonical_extras = _collect_extra_key_map(group.hosts)
    for key_lower in sorted(canonical_extras.keys()):
        canonical_key = canonical_extras[key_lower]
        extra_options = _collect_distinct_values(
            group.hosts,
            [(h.name, _get_extra_value_ci(h, key_lower)) for h in group.hosts],
        )
        if len(extra_options) >= 2:
            conflicts.append(
                FieldConflict(
                    field=f"extra:{canonical_key}",
                    label=f"Extra: {canonical_key}",
                    options=extra_options,
                    allow_empty=True,
                )
            )

    return conflicts


def default_conflict_choices(
    group: DuplicateGroup,
    primary_host_id: str,
    conflicts: list[FieldConflict],
) -> dict[str, str | None]:
    """Waehlt pro Konflikt den Wert des Primary-Hosts (oder den ersten verfuegbaren Wert)."""
    primary = group.get_host_by_id(primary_host_id)
    choices: dict[str, str | None] = {}

    for conflict in conflicts:
        selected: str | None = None
        if primary is not None:
            if conflict.field == "host_name" and primary.host_name.strip():
                selected = primary.host_name.strip()
            elif conflict.field == "identity" and primary.identity:
                selected = primary.identity.strip()
            elif conflict.field == "identity_file" and primary.identity_file:
                selected = primary.identity_file.strip()
            elif conflict.field.startswith("extra:"):
                key_lower = conflict.field.removeprefix("extra:").lower()
                val = _get_extra_value_ci(primary, key_lower)
                if val is not None and val.strip():
                    selected = val.strip()

        if selected is None and conflict.options:
            selected = conflict.options[0].value

        choices[conflict.field] = selected

    return choices


def _ordered_hosts(group: DuplicateGroup, primary: HostEntry) -> list[HostEntry]:
    return [primary, *(host for host in group.hosts if host.id != primary.id)]


def _first_non_empty(values: list[str | None]) -> str | None:
    for value in values:
        if value is not None and value.strip():
            return value.strip()
    return None


def _merge_unique_list(lists: list[list[str]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for items in lists:
        for item in items:
            cleaned = item.strip()
            if cleaned and cleaned not in seen:
                result.append(cleaned)
                seen.add(cleaned)
    return result


def build_merged_host(
    group: DuplicateGroup,
    primary_host_id: str,
    target_name: str,
    resolved_fields: dict[str, str | None] | None = None,
) -> HostEntry:
    """Erstellt den zusammengefuehrten Host auf Basis des Primary-Hosts und der Konfliktwahlen."""
    primary = group.get_host_by_id(primary_host_id)
    if primary is None:
        raise ValueError(f"Primary-Host '{primary_host_id}' ist nicht in der Gruppe enthalten")

    resolved = resolved_fields or {}
    ordered = _ordered_hosts(group, primary)

    merged = copy.deepcopy(primary)
    merged.name = target_name.strip()
    merged.enabled = True

    if "host_name" in resolved and resolved["host_name"]:
        merged.host_name = resolved["host_name"]
    else:
        merged.host_name = primary.host_name.strip()

    merged.user = _first_non_empty([h.user for h in ordered])

    merged.port = next((h.port for h in ordered if h.port is not None), None)

    if "identity" in resolved:
        merged.identity = resolved["identity"]
    else:
        merged.identity = _first_non_empty([h.identity for h in ordered])

    if "identity_file" in resolved:
        merged.identity_file = resolved["identity_file"]
    else:
        merged.identity_file = _first_non_empty([h.identity_file for h in ordered])

    merged.groups = _merge_unique_list([h.groups for h in ordered])
    merged.tags = _merge_unique_list([h.tags for h in ordered])

    canonical_extras = _collect_extra_key_map(ordered)
    resolved_extra_ci: dict[str, str | None] = {}
    for field_name, field_value in resolved.items():
        if field_name.startswith("extra:"):
            resolved_extra_ci[field_name.removeprefix("extra:").lower()] = field_value

    merged_extras: dict[str, str] = {}
    for key_lower in sorted(canonical_extras.keys()):
        canonical_key = canonical_extras[key_lower]
        if key_lower in resolved_extra_ci:
            chosen = resolved_extra_ci[key_lower]
            if chosen is not None and chosen.strip():
                merged_extras[canonical_key] = chosen.strip()
        else:
            value = _first_non_empty([_get_extra_value_ci(h, key_lower) for h in ordered])
            if value is not None:
                merged_extras[canonical_key] = value

    merged.extra_options = merged_extras
    return merged


def apply_merge(
    db: HostDatabase,
    plan: MergePlan,
) -> tuple[HostDatabase, HostEntry, list[str]]:
    """Wendet einen MergePlan transaktional auf einer Kopie der Datenbank an."""
    candidate_db = copy.deepcopy(db)

    primary_in_db = candidate_db.get_by_id(plan.primary_host_id)
    if primary_in_db is None:
        return candidate_db, HostEntry(), ["Primary-Host nicht in der Datenbank gefunden"]

    merged = build_merged_host(
        group=plan.group,
        primary_host_id=plan.primary_host_id,
        target_name=plan.target_name,
        resolved_fields=plan.resolved_fields,
    )

    primary_index = candidate_db.hosts.index(primary_in_db)
    candidate_db.hosts[primary_index] = merged

    duplicate_ids = {host.id for host in plan.group.hosts if host.id != plan.primary_host_id}
    if plan.disposition == "delete":
        candidate_db.hosts = [h for h in candidate_db.hosts if h.id not in duplicate_ids]
    elif plan.disposition == "disable":
        for host in candidate_db.hosts:
            if host.id in duplicate_ids:
                host.enabled = False
    else:
        return candidate_db, merged, [f"Unbekannte Merge-Aktion: {plan.disposition}"]

    candidate_db.ensure_groups(merged.groups)
    errors = candidate_db.validate()
    return candidate_db, merged, errors
