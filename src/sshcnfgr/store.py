from __future__ import annotations

import shutil
import tomllib
from datetime import datetime
from pathlib import Path

import tomli_w

from .model import HostDatabase, HostEntry, HostGroup, IdentityProfile
from .paths import (
    DB_PATH,
    LEGACY_DB_PATH,
    SSH_DIR,
    ensure_private_dir,
    set_private_permissions,
)


def create_backup(path: Path) -> Path | None:
    """Erstellt vor dem Ueberschreiben ein Zeitstempel-Backup einer vorhandenen Datei."""
    if not path.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak.{timestamp}")
    counter = 1
    while backup_path.exists():
        backup_path = path.with_name(f"{path.name}.bak.{timestamp}-{counter}")
        counter += 1

    shutil.copy2(path, backup_path)
    set_private_permissions(backup_path)
    return backup_path


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
    if host.ip is not None:
        payload["ip"] = host.ip
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
    if group.user is not None:
        payload["user"] = group.user
    if group.port is not None:
        payload["port"] = group.port
    if group.extra_options:
        payload["extra_options"] = group.extra_options
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
        ip=str(data["ip"]) if data.get("ip") is not None else None,
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
    extra_raw = data.get("extra_options")
    extra_options: dict[str, str] = {}
    if isinstance(extra_raw, dict):
        extra_options = {str(k): str(v) for k, v in extra_raw.items()}
    return HostGroup(
        name=str(data.get("name", "")),
        description=str(data.get("description", "")) if data.get("description") else "",
        identity=str(data.get("identity", "")) if data.get("identity") else None,
        user=str(data["user"]) if data.get("user") is not None else None,
        port=int(data["port"]) if data.get("port") is not None else None,
        extra_options=extra_options,
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


def load_database(path: Path | None = None) -> HostDatabase:
    target = path if path is not None else DB_PATH
    if not target.exists():
        # Nahtlose Migration: falls ~/.ssh/sshcnfgr.toml noch fehlt, aber die alte
        # ~/.config/sshcnfgr/hosts.toml vorhanden ist, diese einmalig als Quelle laden.
        if path is None and LEGACY_DB_PATH.exists():
            target = LEGACY_DB_PATH
        else:
            return HostDatabase()

    raw = tomllib.loads(target.read_text(encoding="utf-8-sig"))
    group_items = raw.get("groups", [])
    identity_items = raw.get("identities", [])
    global_options_raw = raw.get("global_options", {})
    host_items = raw.get("hosts", [])
    ui_raw = raw.get("ui", {})

    global_options: dict[str, str] = {}
    if isinstance(global_options_raw, dict):
        global_options = {str(k): str(v) for k, v in global_options_raw.items()}

    ui: dict[str, str | bool] = {}
    if isinstance(ui_raw, dict):
        for k, v in ui_raw.items():
            if isinstance(v, (str, bool)):
                ui[str(k)] = v

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

    # Rueckwaertskompatibilitaet: existierende TOML ohne [[groups]]
    # wird automatisch mit referenzierten Gruppen aufgefuellt.
    db = HostDatabase(
        groups=groups,
        identities=identities,
        global_options=global_options,
        hosts=hosts,
        ui=ui,
    )
    referenced_groups = sorted({group for host in hosts for group in host.groups})
    db.ensure_groups(referenced_groups)

    return db


def _read_existing_ui(path: Path) -> dict[str, str | bool]:
    if not path.exists():
        return {}
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    ui_raw = raw.get("ui", {})
    if not isinstance(ui_raw, dict):
        return {}
    return {str(k): v for k, v in ui_raw.items() if isinstance(v, (str, bool))}


def save_database(db: HostDatabase, path: Path = DB_PATH, *, backup: bool = True) -> None:
    if path.parent == SSH_DIR:
        ensure_private_dir(path.parent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)

    ui_section = db.ui if db.ui else _read_existing_ui(path)

    if backup:
        create_backup(path)

    payload: dict[str, object] = {
        # Gruppen-Reihenfolge explizit beibehalten (bestimmt Sortierung in config.generated/VS Code)
        "groups": [_group_to_dict(group) for group in db.ordered_groups()],
        "identities": [_identity_to_dict(identity) for identity in db.sorted_identities()],
        "global_options": db.global_options,
        "hosts": [_host_to_dict(host) for host in db.sorted_hosts()],
    }
    if ui_section:
        payload["ui"] = ui_section

    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(tomli_w.dumps(payload), encoding="utf-8")
    set_private_permissions(tmp_path)
    tmp_path.replace(path)
