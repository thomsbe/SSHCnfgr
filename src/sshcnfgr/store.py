from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w

from .model import HostDatabase, HostEntry, HostGroup, IdentityProfile
from .paths import DB_PATH


def _host_to_dict(host: HostEntry) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": host.id,
        "name": host.name,
        "enabled": host.enabled,
        "host_name": host.host_name,
        "groups": host.groups,
        "tags": host.tags,
        "extra_options": host.extra_options,
    }

    # tomli-w serialisiert kein None, daher optionale Felder nur bei Wert schreiben.
    if host.user is not None:
        payload["user"] = host.user
    if host.port is not None:
        payload["port"] = host.port
    if host.identity is not None:
        payload["identity"] = host.identity
    if host.identity_file is not None:
        payload["identity_file"] = host.identity_file

    return payload


def _group_to_dict(group: HostGroup) -> dict[str, object]:
    payload: dict[str, object] = {"name": group.name}
    if group.description:
        payload["description"] = group.description
    if group.identity:
        payload["identity"] = group.identity
    return payload


def _identity_to_dict(identity: IdentityProfile) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": identity.name,
        "identity_file": identity.identity_file,
        "source": identity.source,
        "enabled": identity.enabled,
    }
    if identity.public_key_file:
        payload["public_key_file"] = identity.public_key_file
    if identity.public_key_preview:
        payload["public_key_preview"] = identity.public_key_preview
    return payload


def _host_from_dict(data: dict[str, object]) -> HostEntry:
    return HostEntry(
        id=str(data.get("id", "")) or HostEntry().id,
        name=str(data.get("name", "")),
        enabled=bool(data.get("enabled", True)),
        host_name=str(data.get("host_name", "")),
        user=str(data["user"]) if data.get("user") is not None else None,
        port=int(data["port"]) if data.get("port") is not None else None,
        identity=str(data["identity"]) if data.get("identity") is not None else None,
        identity_file=str(data["identity_file"]) if data.get("identity_file") is not None else None,
        groups=[str(group) for group in (data.get("groups") or [])],
        tags=[str(tag) for tag in (data.get("tags") or [])],
        extra_options={
            str(k): str(v) for k, v in (data.get("extra_options") or {}).items()  # type: ignore[arg-type]
        },
    )


def _group_from_dict(data: dict[str, object]) -> HostGroup:
    return HostGroup(
        name=str(data.get("name", "")),
        description=str(data.get("description", "")) if data.get("description") else "",
        identity=str(data.get("identity", "")) if data.get("identity") else None,
    )


def _identity_from_dict(data: dict[str, object]) -> IdentityProfile:
    return IdentityProfile(
        name=str(data.get("name", "")),
        identity_file=str(data.get("identity_file", "")),
        source=str(data.get("source", "manual")),
        public_key_file=str(data.get("public_key_file", ""))
        if data.get("public_key_file")
        else None,
        public_key_preview=str(data.get("public_key_preview", ""))
        if data.get("public_key_preview")
        else None,
        enabled=bool(data.get("enabled", True)),
    )


def load_database(path: Path = DB_PATH) -> HostDatabase:
    if not path.exists():
        return HostDatabase()

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    group_items = raw.get("groups", [])
    identity_items = raw.get("identities", [])
    global_options_raw = raw.get("global_options", {})
    host_items = raw.get("hosts", [])

    global_options: dict[str, str] = {}
    if isinstance(global_options_raw, dict):
        global_options = {str(k): str(v) for k, v in global_options_raw.items()}

    groups: list[HostGroup] = []
    for item in group_items:
        if isinstance(item, dict):
            group = _group_from_dict(item)
            if group.name:
                groups.append(group)

    identities: list[IdentityProfile] = []
    for item in identity_items:
        if isinstance(item, dict):
            identity = _identity_from_dict(item)
            if identity.name and identity.identity_file:
                identities.append(identity)

    hosts: list[HostEntry] = []
    for item in host_items:
        if isinstance(item, dict):
            hosts.append(_host_from_dict(item))

    # Rueckwaertskompatibilitaet: existierende hosts.toml ohne [groups]
    # wird automatisch mit referenzierten Gruppen aufgefuellt.
    db = HostDatabase(
        groups=groups,
        identities=identities,
        global_options=global_options,
        hosts=hosts,
    )
    referenced_groups = sorted({group for host in hosts for group in host.groups})
    db.ensure_groups(referenced_groups)

    return db


def save_database(db: HostDatabase, path: Path = DB_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "groups": [_group_to_dict(group) for group in db.sorted_groups()],
        "identities": [_identity_to_dict(identity) for identity in db.sorted_identities()],
        "global_options": db.global_options,
        "hosts": [_host_to_dict(host) for host in db.hosts],
    }

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(tomli_w.dumps(payload), encoding="utf-8")
    tmp_path.replace(path)
