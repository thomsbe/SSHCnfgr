from __future__ import annotations

from pathlib import Path

from loguru import logger

from .model import HostDatabase, HostEntry

KNOWN_DIRECTIVES = {
    "hostname": "host_name",
    "user": "user",
    "port": "port",
    "identityfile": "identity_file",
}


class ImportReport:
    def __init__(self) -> None:
        self.imported_hosts = 0
        self.renamed_hosts = 0
        self.warnings: list[str] = []

    def summary(self) -> str:
        return (
            f"imported={self.imported_hosts}, renamed={self.renamed_hosts}, "
            f"warnings={len(self.warnings)}"
        )


def _unique_name(candidate: str, seen: set[str]) -> tuple[str, bool]:
    if candidate not in seen:
        return candidate, False

    index = 1
    while f"{candidate}-{index}" in seen:
        index += 1
    return f"{candidate}-{index}", True


def import_ssh_config(path: Path) -> tuple[HostDatabase, ImportReport]:
    report = ImportReport()
    if not path.exists():
        raise FileNotFoundError(f"Config nicht gefunden: {path}")

    hosts: list[HostEntry] = []
    global_options: dict[str, str] = {}
    seen_names: set[str] = set()
    current_hosts: list[HostEntry] = []
    in_host_wildcard = False
    in_skipped_host = False
    seen_host_block = False

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if " " not in line and "\t" not in line:
            report.warnings.append(f"Zeile {line_number}: kann nicht geparst werden: {raw_line}")
            continue

        key, value = line.split(maxsplit=1)
        key_lower = key.lower()

        if key_lower == "host":
            names = [token for token in value.split() if token]
            current_hosts = []
            in_host_wildcard = names == ["*"]
            in_skipped_host = False
            seen_host_block = True

            if in_host_wildcard:
                continue

            for name in names:
                if any(ch in name for ch in "*?!"):
                    report.warnings.append(
                        f"Zeile {line_number}: Wildcard-Host '{name}' wurde uebersprungen"
                    )
                    continue

                unique_name, renamed = _unique_name(name, seen_names)
                seen_names.add(unique_name)

                host = HostEntry(name=unique_name, host_name=unique_name, enabled=True)
                current_hosts.append(host)
                hosts.append(host)
                report.imported_hosts += 1
                if renamed:
                    report.renamed_hosts += 1
                    report.warnings.append(
                        f"Zeile {line_number}: Host '{name}' umbenannt zu '{unique_name}'"
                    )

            # Komplett uebersprungene Bloecke (z. B. nur Wildcards) duerfen ihre
            # Direktiven nicht an nachfolgende Hosts oder global_options verlieren.
            in_skipped_host = not current_hosts
            continue

        if in_host_wildcard:
            global_options[key] = value
            continue

        if in_skipped_host:
            report.warnings.append(
                f"Zeile {line_number}: Direktive fuer uebersprungenen Host-Block ignoriert ({key})"
            )
            continue

        if not seen_host_block:
            # Direktiven vor dem ersten Host-Block (inkl. Include) gelten in
            # OpenSSH als globale Defaults und gehoeren nicht an einen Host.
            global_options[key] = value
            continue

        for host in current_hosts:
            field_name = KNOWN_DIRECTIVES.get(key_lower)
            if field_name == "host_name":
                host.host_name = value
            elif field_name == "user":
                host.user = value
            elif field_name == "port":
                try:
                    host.port = int(value)
                except ValueError:
                    report.warnings.append(
                        f"Zeile {line_number}: Port '{value}' ist ungueltig fuer Host '{host.name}'"
                    )
            elif field_name == "identity_file":
                host.identity_file = value
            else:
                host.extra_options[key] = value

    logger.info("Import abgeschlossen: {}", report.summary())
    db = HostDatabase(hosts=hosts, global_options=global_options)
    return db, report
