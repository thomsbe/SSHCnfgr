from __future__ import annotations

from pathlib import Path

import click
from loguru import logger

from .generator import write_generated_config
from .identities import discover_ssh_identities, merge_discovered_identities
from .importer import import_ssh_config
from .logging_conf import configure_logging
from .paths import DB_PATH, GENERATED_CONFIG_PATH
from .store import load_database, save_database
from .tui import run_tui


@click.group(help="SSHCnfgr: SSH-Hosts per TOML mit TUI und CLI verwalten")
@click.option("--verbose", is_flag=True, help="Debug-Logging aktivieren")
def cli(verbose: bool) -> None:
    configure_logging(verbose=verbose)


@cli.command("tui", help="Starte die Textual TUI")
def tui_command() -> None:
    logger.info("TUI wird gestartet")
    run_tui()


@cli.command("import", help="Importiere eine bestehende SSH-Config in die TOML-Datenbank")
@click.option(
    "--source",
    type=click.Path(path_type=Path, exists=True, dir_okay=False, file_okay=True),
    default=Path.home() / ".ssh" / "config",
    show_default=True,
)
def import_command(source: Path) -> None:
    db, report = import_ssh_config(source)
    errors = db.validate()
    if errors:
        for err in errors:
            logger.error(err)
        raise click.ClickException("Import erzeugt ungueltige Daten")

    save_database(db, DB_PATH)

    logger.info("Import abgeschlossen: {}", report.summary())
    for warning in report.warnings:
        logger.warning(warning)

    click.echo(f"Import ok: {report.summary()}")


@cli.command("generate", help="Generiere eine OpenSSH-Config aus der TOML-Datenbank")
@click.option(
    "--output",
    type=click.Path(path_type=Path, dir_okay=False, file_okay=True),
    default=GENERATED_CONFIG_PATH,
    show_default=True,
)
def generate_command(output: Path) -> None:
    db = load_database(DB_PATH)
    errors = db.validate()
    if errors:
        for err in errors:
            logger.error(err)
        raise click.ClickException("Datenbank ist ungueltig, Generierung abgebrochen")

    target = write_generated_config(db, output=output)
    logger.info("Config generiert: {}", target)
    click.echo(f"Generiert: {target}")


@cli.group("identities", help="Identities verwalten")
def identities_group() -> None:
    pass


@identities_group.command("scan", help="Lese Identities direkt aus ~/.ssh ein")
@click.option(
    "--ssh-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True),
    default=Path.home() / ".ssh",
    show_default=True,
)
def identities_scan_command(ssh_dir: Path) -> None:
    db = load_database(DB_PATH)
    discovered = discover_ssh_identities(ssh_dir)
    created, updated = merge_discovered_identities(db, discovered)
    save_database(db, DB_PATH)
    logger.info("Identities gescannt: discovered={}, created={}, updated={}", len(discovered), created, updated)
    click.echo(f"Scan ok: discovered={len(discovered)} created={created} updated={updated}")


@identities_group.command("list", help="Liste bekannte Identities")
def identities_list_command() -> None:
    db = load_database(DB_PATH)
    if not db.identities:
        click.echo("Keine Identities vorhanden")
        return

    for identity in db.sorted_identities():
        click.echo(
            f"{identity.name:20} {identity.identity_file} source={identity.source} enabled={identity.enabled}"
        )


@cli.group("groups", help="Gruppen verwalten")
def groups_group() -> None:
    pass


@groups_group.command("set-identity", help="Setze eine Identity fuer eine Gruppe")
@click.argument("group_name")
@click.argument("identity_name")
def groups_set_identity_command(group_name: str, identity_name: str) -> None:
    db = load_database(DB_PATH)

    identity = db.get_identity_by_name(identity_name)
    if identity is None:
        raise click.ClickException(f"Identity nicht gefunden: {identity_name}")

    group = db.get_group_by_name(group_name)
    if group is None:
        db.ensure_groups([group_name])
        group = db.get_group_by_name(group_name)
        assert group is not None

    group.identity = identity.name

    errors = db.validate()
    if errors:
        raise click.ClickException("; ".join(errors))

    save_database(db, DB_PATH)
    click.echo(f"Group '{group.name}' nutzt jetzt Identity '{identity.name}'")


if __name__ == "__main__":
    cli()
