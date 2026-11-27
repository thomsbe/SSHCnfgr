from __future__ import annotations

import copy
import ipaddress
import re
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .dedup import is_ip_address, normalize_ip
from .model import HostDatabase, HostEntry

_UNSAFE_ALIAS_RE = re.compile(r"[\s*?!]+")

CanonResolver = Callable[[str], tuple[str | None, list[str]]]
ReverseResolver = Callable[[str], str | None]


@dataclass(slots=True)
class DnsEnrichResult:
    """Ergebnis einer DNS-Anreicherung (FQDN + IP) fuer einen einzelnen Host."""

    host_id: str
    fqdn: str | None = None
    ip: str | None = None

    @property
    def resolved(self) -> bool:
        return bool(self.fqdn or self.ip)


def _prefer_ipv4_order(raw_ips: list[str]) -> list[str]:
    ipv4: list[str] = []
    ipv6: list[str] = []
    seen: set[str] = set()
    for raw in raw_ips:
        norm = normalize_ip(raw)
        if norm is None or norm in seen:
            continue
        seen.add(norm)
        addr = ipaddress.ip_address(norm)
        if addr.version == 4:
            ipv4.append(norm)
        else:
            ipv6.append(norm)
    return [*ipv4, *ipv6]


def _default_canon_resolve(hostname: str) -> tuple[str | None, list[str]]:
    try:
        infos = socket.getaddrinfo(
            hostname,
            None,
            type=socket.SOCK_STREAM,
            flags=socket.AI_CANONNAME,
        )
    except (socket.gaierror, OSError):
        return None, []

    canon: str | None = None
    ips: list[str] = []
    for info in infos:
        if canon is None and info[3]:
            cleaned_canon = str(info[3]).strip().rstrip(".")
            if cleaned_canon and normalize_ip(cleaned_canon) is None:
                canon = cleaned_canon
        sockaddr = info[4]
        if sockaddr:
            ips.append(str(sockaddr[0]))

    return canon, _prefer_ipv4_order(ips)


def _default_reverse_resolve(ip_addr: str) -> str | None:
    try:
        hostname, _, _ = socket.gethostbyaddr(ip_addr)
    except (socket.herror, socket.gaierror, OSError):
        return None
    cleaned = hostname.strip().rstrip(".")
    if not cleaned or normalize_ip(cleaned) is not None:
        return None
    return cleaned


def resolve_fqdn_and_ip(
    host_name: str,
    *,
    canon_resolver: CanonResolver | None = None,
    reverse_resolver: ReverseResolver | None = None,
) -> tuple[str | None, str | None]:
    """Ermittelt FQDN und IP zu einem HostName.

    - Kurzname ohne Punkt (z. B. ``sdvdmg-mongodb``): erweitert per AI_CANONNAME
      oder PTR auf den vollen FQDN (z. B. ``sdvdmg-mongodb.slub-dresden.de``) + IP.
    - Direkte IP: ermittelt per Forward-Confirmed Reverse DNS (FCrDNS) den FQDN
      und behaelt die IP als ``ip``.
    - Bereits vollstaendiger FQDN (mit Punkt): ueberschreibt CNAMEs nicht blind,
      sondern ergaenzt gezielt die aufgeloeste IP.
    """
    cleaned = host_name.strip()
    if not cleaned:
        return None, None

    canon_fn = canon_resolver or _default_canon_resolve
    rev_fn = reverse_resolver or _default_reverse_resolve

    ip_literal = normalize_ip(cleaned)
    if ip_literal is not None:
        ptr = rev_fn(ip_literal)
        if ptr:
            ptr_clean = ptr.strip().rstrip(".")
            if ptr_clean and not is_ip_address(ptr_clean):
                # Forward-Confirmed Reverse DNS (FCrDNS): PTR nur uebernehmen,
                # wenn der Name auch wieder auf diese IP aufloest.
                _, fwd_ips = canon_fn(ptr_clean)
                if ip_literal in _prefer_ipv4_order(fwd_ips):
                    return ptr_clean, ip_literal
        return None, ip_literal

    canon, raw_ips = canon_fn(cleaned)
    ordered_ips = _prefer_ipv4_order(raw_ips)
    best_ip = ordered_ips[0] if ordered_ips else None

    if "." in cleaned:
        # Bereits ein FQDN: nicht gegen abweichenden CNAME-Zielnamen ersetzen,
        # sondern die IP sauber ergaenzen.
        return None, best_ip

    # Kurzname ohne Punkt -> versuchen, auf vollen FQDN (mit Domain) zu erweitern.
    if canon and "." in canon and not is_ip_address(canon):
        return canon, best_ip

    if best_ip is not None:
        ptr = rev_fn(best_ip)
        if ptr and "." in ptr and not is_ip_address(ptr):
            ptr_clean = ptr.strip().rstrip(".")
            if ptr_clean.lower().startswith(cleaned.lower() + "."):
                return ptr_clean, best_ip
            _, fwd_ips = canon_fn(ptr_clean)
            if best_ip in _prefer_ipv4_order(fwd_ips):
                return ptr_clean, best_ip

    return None, best_ip


def enrich_hosts_dns(
    hosts: list[HostEntry],
    *,
    max_workers: int = 10,
    canon_resolver: CanonResolver | None = None,
    reverse_resolver: ReverseResolver | None = None,
) -> dict[str, DnsEnrichResult]:
    """Loest fuer eine Liste von Hosts parallel FQDN und IP auf."""
    unique_names: list[str] = []
    seen: set[str] = set()
    for host in hosts:
        key = host.host_name.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique_names.append(host.host_name.strip())

    resolved_by_key: dict[str, tuple[str | None, str | None]] = {}
    if unique_names:
        workers = max(1, min(max_workers, len(unique_names)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    resolve_fqdn_and_ip,
                    raw_name,
                    canon_resolver=canon_resolver,
                    reverse_resolver=reverse_resolver,
                ): raw_name.lower()
                for raw_name in unique_names
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    resolved_by_key[key] = future.result()
                except Exception:
                    resolved_by_key[key] = (None, None)

    results: dict[str, DnsEnrichResult] = {}
    for host in hosts:
        key = host.host_name.strip().lower()
        fqdn, ip_addr = resolved_by_key.get(key, (None, None))
        results[host.id] = DnsEnrichResult(host_id=host.id, fqdn=fqdn, ip=ip_addr)
    return results


def apply_dns_enrichment(
    db: HostDatabase,
    host_ids: set[str],
    results: dict[str, DnsEnrichResult],
) -> tuple[HostDatabase, int, int, list[str]]:
    """Wendet DNS-Anreicherung (FQDN + IP) transaktional auf einer Kopie der DB an.

    Rueckgabe: (candidate_db, updated_count, unresolved_count, validation_errors)
    """
    candidate_db = copy.deepcopy(db)
    updated = 0
    unresolved = 0

    for host in candidate_db.hosts:
        if host.id not in host_ids:
            continue
        res = results.get(host.id)
        if res is None or not res.resolved:
            unresolved += 1
            continue

        host_changed = False
        if res.fqdn and res.fqdn != host.host_name:
            host.host_name = res.fqdn
            host_changed = True
        if res.ip and res.ip != host.ip:
            host.ip = res.ip
            host_changed = True

        if host_changed:
            updated += 1

    errors = candidate_db.validate()
    return candidate_db, updated, unresolved, errors


def build_alias_base(host: HostEntry, db: HostDatabase) -> str:
    """Erzeugt den Basis-Alias im Format USER@kurzname (oder USER@ip / kurzname)."""
    raw_host = host.host_name.strip()
    if not raw_host:
        return ""

    ip_norm = normalize_ip(raw_host)
    if ip_norm is not None:
        host_part = ip_norm
    else:
        host_part = raw_host.split(".", 1)[0].strip().lower()

    host_part = _UNSAFE_ALIAS_RE.sub("-", host_part).strip("-")
    if not host_part:
        return ""

    effective_user = (db.resolve_user(host) or "").strip()
    effective_user = _UNSAFE_ALIAS_RE.sub("", effective_user)
    if effective_user:
        return f"{effective_user}@{host_part}"
    return host_part


def suggest_host_alias(
    host: HostEntry,
    db: HostDatabase,
    *,
    reserved_names: set[str] | None = None,
) -> str:
    """Schlaegt einen eindeutigen Alias im Format USER@kurzname (mit -2/-3 bei Kollision) vor."""
    base = build_alias_base(host, db)
    if not base:
        return host.name

    taken = {h.name for h in db.hosts if h.id != host.id}
    if reserved_names:
        taken.update(reserved_names)

    if base not in taken:
        return base

    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def bulk_generate_aliases(
    db: HostDatabase,
    host_ids: set[str],
) -> tuple[HostDatabase, list[tuple[str, str]], list[str]]:
    """Benennt mehrere Hosts transaktional nach dem Schema USER@kurzname um.

    Rueckgabe: (candidate_db, renames[(old_name, new_name)], validation_errors)
    """
    candidate_db = copy.deepcopy(db)
    reserved = {h.name for h in candidate_db.hosts if h.id not in host_ids}
    renames: list[tuple[str, str]] = []

    for host in candidate_db.ordered_hosts_by_group():
        if host.id not in host_ids:
            continue
        new_alias = suggest_host_alias(host, candidate_db, reserved_names=reserved)
        reserved.add(new_alias)
        if new_alias != host.name:
            renames.append((host.name, new_alias))
            host.name = new_alias

    errors = candidate_db.validate()
    return candidate_db, renames, errors
