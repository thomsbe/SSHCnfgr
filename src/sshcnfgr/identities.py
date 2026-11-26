from __future__ import annotations

from pathlib import Path

from .model import HostDatabase, IdentityProfile

IGNORED_FILES = {
    "config",
    "known_hosts",
    "known_hosts.old",
    "authorized_keys",
}


def _parse_public_key_preview(public_key_file: Path) -> str | None:
    try:
        line = public_key_file.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return None

    parts = line.split()
    if not parts:
        return None

    key_type = parts[0]
    comment = parts[2] if len(parts) >= 3 else ""
    if comment:
        return f"{key_type} {comment}"
    return key_type


def discover_ssh_identities(ssh_dir: Path | None = None) -> list[IdentityProfile]:
    base_dir = ssh_dir or (Path.home() / ".ssh")
    if not base_dir.exists() or not base_dir.is_dir():
        return []

    identities: list[IdentityProfile] = []
    for candidate in sorted(base_dir.iterdir(), key=lambda path: path.name.lower()):
        if not candidate.is_file():
            continue
        if candidate.name in IGNORED_FILES:
            continue
        if candidate.suffix == ".pub":
            continue

        public_key_candidate = candidate.with_name(candidate.name + ".pub")
        if not public_key_candidate.exists():
            # Fuer den Start nehmen wir nur Keys mit vorhandenem Public-Key-File auf,
            # um den Datensatz in der UI besser erklaeren zu koennen.
            continue

        preview = _parse_public_key_preview(public_key_candidate)
        identities.append(
            IdentityProfile(
                name=candidate.name,
                identity_file=str(candidate),
                source="local-ssh",
                public_key_file=str(public_key_candidate),
                public_key_preview=preview,
                enabled=True,
            )
        )

    return identities


def merge_discovered_identities(
    db: HostDatabase, discovered: list[IdentityProfile]
) -> tuple[int, int]:
    existing_by_name = {identity.name: identity for identity in db.identities}
    existing_paths = {identity.identity_file for identity in db.identities}

    created = 0
    updated = 0

    for profile in discovered:
        existing = existing_by_name.get(profile.name)
        if existing:
            existing.identity_file = profile.identity_file
            existing.source = profile.source
            existing.public_key_file = profile.public_key_file
            existing.public_key_preview = profile.public_key_preview
            updated += 1
            continue

        if profile.identity_file in existing_paths:
            # Bereits durch ein anderes Profil abgedeckt.
            continue

        db.identities.append(profile)
        existing_by_name[profile.name] = profile
        existing_paths.add(profile.identity_file)
        created += 1

    return created, updated
