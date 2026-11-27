from __future__ import annotations

import copy
import ipaddress
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Literal

from .model import HostDatabase, HostEntry

MergeDisposition = Literal["disable", "delete"]


def normalize_ip(value: str) -> str | None:
    """Gibt eine normalisierte IPv4/IPv6-Adresse zurueck oder None bei Hostnamen."""
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return str(ipaddress.ip_address(cleaned))
    except ValueError:
        return None


def is_ip_address(value: str) -> bool:
    """Prueft, ob ein String eine direkte IPv4- oder IPv6-Adresse ist."""
    return normalize_ip(value) is not None


@dataclass(slots=True)
class DnsResolutionMap:
    """Ergebnis eines explizit angestossenen DNS-Checks (Forward Name->IP & Reverse PTR)."""

    ips_by_host: dict[str, set[str]] = field(default_factory=dict)
    ptr_by_ip: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    resolved_count: int = 0
    ptr_count: int = 0

    def describe_host_name(self, host_name: str) -> str:
        """Kurze Anzeige fuer Tabellen: aufgeloeste IPs oder PTR-Hinweis."""
        norm = host_name.strip().lower()
        if not norm:
            return ""
        ip_literal = normalize_ip(norm)
        if ip_literal is not None:
            ptr = self.ptr_by_ip.get(ip_literal)
            return f"PTR: {ptr}" if ptr else ""

        ips = sorted(self.ips_by_host.get(norm, set()))
        if not ips:
            return "(nicht aufloesbar)" if norm in self.unresolved else ""
        if len(ips) <= 2:
            return ", ".join(ips)
        return f"{ips[0]}, {ips[1]} (+{len(ips) - 2})"

    def summary(self) -> str:
        parts = [f"{self.resolved_count} aufgeloest"]
        if self.unresolved:
            parts.append(f"{len(self.unresolved)} nicht aufloesbar")
        if self.ptr_count:
            parts.append(f"{self.ptr_count} PTR-Hinweise")
        return ", ".join(parts)


def _default_forward_resolve(hostname: str) -> set[str]:
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return set()

    ips: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = normalize_ip(str(sockaddr[0]))
        if ip_str is not None:
            ips.add(ip_str)
    return ips


def _default_reverse_resolve(ip_addr: str) -> str | None:
    try:
        hostname, _, _ = socket.gethostbyaddr(ip_addr)
    except (socket.herror, socket.gaierror, OSError):
        return None
    cleaned = hostname.strip().rstrip(".")
    if not cleaned or normalize_ip(cleaned) is not None:
        return None
    return cleaned


def resolve_hostnames_dns(
    hosts: list[HostEntry],
    *,
    max_workers: int = 10,
    include_ptr: bool = True,
    forward_resolver: Callable[[str], set[str]] | None = None,
    reverse_resolver: Callable[[str], str | None] | None = None,
) -> DnsResolutionMap:
    """Loest Hostnamen parallel per Forward-DNS (Name->IP) und optional PTR (IP->Name) auf.

    Wird bewusst nur auf Nutzeraktion (Button) aufgerufen, niemals automatisch beim Start.
    """
    fwd = forward_resolver or _default_forward_resolve
    rev = reverse_resolver or _default_reverse_resolve

    ips_by_host: dict[str, set[str]] = {}
    ptr_by_ip: dict[str, str] = {}
    names_to_resolve: list[str] = []
    literal_ips: set[str] = set()

    seen_names: set[str] = set()
    for host in hosts:
        norm = host.host_name.strip().lower()
        if not norm or norm in seen_names:
            continue
        seen_names.add(norm)

        ip_literal = normalize_ip(norm)
        if ip_literal is not None:
            ips_by_host[norm] = {ip_literal}
            literal_ips.add(ip_literal)
        else:
            names_to_resolve.append(norm)

    unresolved: list[str] = []
    resolved_count = 0

    total_tasks = len(names_to_resolve) + (len(literal_ips) if include_ptr else 0)
    if total_tasks == 0:
        return DnsResolutionMap(ips_by_host=ips_by_host)

    worker_count = max(1, min(max_workers, total_tasks))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        fwd_futures = {pool.submit(fwd, name): name for name in names_to_resolve}
        rev_futures = (
            {pool.submit(rev, ip): ip for ip in sorted(literal_ips)} if include_ptr else {}
        )

        for future in as_completed(fwd_futures):
            name = fwd_futures[future]
            try:
                raw_ips = future.result()
            except Exception:
                raw_ips = set()
            normalized_ips = {
                ip_norm for raw_ip in raw_ips if (ip_norm := normalize_ip(raw_ip)) is not None
            }
            if normalized_ips:
                ips_by_host[name] = normalized_ips
                resolved_count += 1
            else:
                unresolved.append(name)

        for future in as_completed(rev_futures):
            ip = rev_futures[future]
            try:
                ptr = future.result()
            except Exception:
                ptr = None
            if ptr:
                cleaned = ptr.strip().rstrip(".")
                if cleaned and normalize_ip(cleaned) is None:
                    ptr_by_ip[ip] = cleaned

    return DnsResolutionMap(
        ips_by_host=ips_by_host,
        ptr_by_ip=ptr_by_ip,
        unresolved=sorted(unresolved),
        resolved_count=resolved_count,
        ptr_count=len(ptr_by_ip),
    )


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
    """Gruppe von Hosts mit identischem Ziel (HostName oder aufgeloeste IP + Port + User)."""

    host_name: str
    port: int
    user: str
    hosts: list[HostEntry] = field(default_factory=list)
    match_source: str = "exact"
    matched_ips: list[str] = field(default_factory=list)
    ptr_names: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, int, str]:
        return (self.host_name, self.port, self.user)

    @property
    def label(self) -> str:
        if self.user:
            return f"{self.user}@{self.host_name}:{self.port}"
        return f"{self.host_name}:{self.port}"

    @property
    def match_badge(self) -> str:
        if self.match_source == "dns":
            if self.matched_ips:
                preview = ", ".join(self.matched_ips[:2])
                if len(self.matched_ips) > 2:
                    preview += f" (+{len(self.matched_ips) - 2})"
                return f"DNS ({preview})"
            return "DNS"
        return "Exakt"

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


def _find_exact_duplicate_groups(
    db: HostDatabase, *, include_inactive: bool = False
) -> list[DuplicateGroup]:
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
                    match_source="exact",
                )
            )
    return groups


def find_duplicate_groups(
    db: HostDatabase,
    *,
    include_inactive: bool = False,
    dns_map: DnsResolutionMap | None = None,
) -> list[DuplicateGroup]:
    """Findet potentielle Dubletten mit gleichem Ziel (HostName/IP, Port, User).

    Ist ``dns_map`` angegeben, werden zusaetzlich Hosts mit gleichem Port/User
    zusammengefasst, die auf mindestens eine gemeinsame IP-Adresse aufloesen.
    """
    if dns_map is None:
        return _find_exact_duplicate_groups(db, include_inactive=include_inactive)

    by_port_user: dict[tuple[int, str], list[HostEntry]] = {}
    for host in db.sorted_hosts():
        if not include_inactive and not host.enabled:
            continue
        if not host.host_name.strip():
            continue
        effective_port = db.resolve_port(host)
        effective_user = (db.resolve_user(host) or "").strip()
        by_port_user.setdefault((effective_port, effective_user), []).append(host)

    groups: list[DuplicateGroup] = []

    for (port, user), bucket_hosts in sorted(by_port_user.items()):
        if len(bucket_hosts) < 2:
            continue

        # Union-Find innerhalb des (port, user)-Buckets:
        # verbindet identische HostNames sowie gemeinsame aufgeloeste IPs.
        parent = list(range(len(bucket_hosts)))

        def _find(idx: int) -> int:
            while parent[idx] != idx:
                parent[idx] = parent[parent[idx]]
                idx = parent[idx]
            return idx

        def _union(a: int, b: int) -> None:
            ra, rb = _find(a), _find(b)
            if ra != rb:
                parent[rb] = ra

        first_by_name: dict[str, int] = {}
        first_by_ip: dict[str, int] = {}

        for idx, host in enumerate(bucket_hosts):
            norm_name = host.host_name.strip().lower()
            if norm_name in first_by_name:
                _union(first_by_name[norm_name], idx)
            else:
                first_by_name[norm_name] = idx

            host_ips = dns_map.ips_by_host.get(norm_name)
            if host_ips is None:
                ip_literal = normalize_ip(norm_name)
                host_ips = {ip_literal} if ip_literal is not None else set()

            for ip_addr in host_ips:
                if ip_addr in first_by_ip:
                    _union(first_by_ip[ip_addr], idx)
                else:
                    first_by_ip[ip_addr] = idx

        components: dict[int, list[HostEntry]] = {}
        for idx, host in enumerate(bucket_hosts):
            components.setdefault(_find(idx), []).append(host)

        for members in components.values():
            if len(members) < 2:
                continue

            sorted_members = sorted(members, key=lambda h: h.name.lower())
            distinct_names = sorted({h.host_name.strip().lower() for h in sorted_members})

            ip_to_names: dict[str, set[str]] = {}
            all_ips: set[str] = set()
            for norm_name in distinct_names:
                resolved_ips = dns_map.ips_by_host.get(norm_name)
                if resolved_ips is None:
                    ip_literal = normalize_ip(norm_name)
                    resolved_ips = {ip_literal} if ip_literal is not None else set()
                for ip_addr in resolved_ips:
                    all_ips.add(ip_addr)
                    ip_to_names.setdefault(ip_addr, set()).add(norm_name)

            if len(distinct_names) == 1:
                match_source = "exact"
                display_host = distinct_names[0]
                matched_ips = sorted(all_ips)
            else:
                match_source = "dns"
                shared_ips = sorted(ip for ip, names in ip_to_names.items() if len(names) >= 2)
                matched_ips = shared_ips or sorted(all_ips)
                non_ip_names = [n for n in distinct_names if not is_ip_address(n)]
                display_host = non_ip_names[0] if non_ip_names else matched_ips[0]

            existing_lower = set(distinct_names)
            ptr_names = sorted(
                {
                    ptr
                    for ip_addr in all_ips
                    if (ptr := dns_map.ptr_by_ip.get(ip_addr))
                    and ptr.lower() not in existing_lower
                }
            )

            groups.append(
                DuplicateGroup(
                    host_name=display_host,
                    port=port,
                    user=user,
                    hosts=sorted_members,
                    match_source=match_source,
                    matched_ips=matched_ips,
                    ptr_names=ptr_names,
                )
            )

    return sorted(groups, key=lambda g: (g.host_name, g.port, g.user))


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
    existing_host_values_lower = {
        opt.value.lower() for opt in host_name_options if opt.value is not None
    }
    ptr_options = [
        ConflictOption(value=ptr, sources=["PTR"])
        for ptr in group.ptr_names
        if ptr.lower() not in existing_host_values_lower
    ]
    all_host_name_options = [*host_name_options, *ptr_options]

    if len(all_host_name_options) >= 2:
        conflicts.append(
            FieldConflict(
                field="host_name",
                label="HostName",
                options=all_host_name_options,
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
    """Waehlt pro Konflikt einen sinnvollen Standardwert.

    Bei einem HostName-Konflikt zwischen Name und IP wird ein sprechender Hostname
    aus einem der Host-Eintraege bevorzugt.
    """
    primary = group.get_host_by_id(primary_host_id)
    choices: dict[str, str | None] = {}

    for conflict in conflicts:
        selected: str | None = None
        if conflict.field == "host_name":
            if primary is not None and primary.host_name.strip():
                primary_hn = primary.host_name.strip()
                if not is_ip_address(primary_hn):
                    selected = primary_hn
            if selected is None:
                # Bevorzuge einen echten Hostnamen aus den Host-Eintraegen (nicht PTR).
                for opt in conflict.options:
                    if opt.value and opt.sources != ["PTR"] and not is_ip_address(opt.value):
                        selected = opt.value
                        break
            if selected is None and primary is not None and primary.host_name.strip():
                selected = primary.host_name.strip()
        elif primary is not None:
            if conflict.field == "identity" and primary.identity:
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

    # IP-Feld uebernehmen: entweder explizites host.ip oder eine zusammengefuhrte IP-HostName.
    explicit_ip = _first_non_empty([h.ip for h in ordered])
    if explicit_ip:
        merged.ip = explicit_ip
    elif not is_ip_address(merged.host_name):
        fallback_ip = next(
            (ip_norm for h in ordered if (ip_norm := normalize_ip(h.host_name)) is not None),
            None,
        )
        if fallback_ip:
            merged.ip = fallback_ip

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
