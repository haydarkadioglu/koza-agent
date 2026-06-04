"""Typer-based Koza CLI command tree.

This module owns the public command interface while preserving the existing
cmd_*(args: list[str]) business logic during the migration.
"""
from __future__ import annotations

from typing import Optional

import typer

from cli.coding_cmd import cmd_coding
from cli.commands import (
    cmd_clean,
    cmd_config,
    cmd_help,
    cmd_kanban,
    cmd_logs,
    cmd_sessions,
    cmd_sync,
    cmd_telegram,
    cmd_uninstall,
    cmd_update,
    cmd_version,
)
from cli.daemon import cmd_quit, cmd_start, cmd_status
from cli.setup import cmd_provider, cmd_setup
from cli.tui_cmd import cmd_tui
from cli.voice_cmd import cmd_voice

app = typer.Typer(
    add_completion=True,
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Koza autonomous AI agent.",
)
sessions_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Browse, load, or delete saved sessions.",
)
provider_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Show and switch the active provider/model.",
)
voice_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Configure or start voice mode.",
)
sync_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Multi-host sync commands.",
)
coding_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Multi-persona coding mode commands.",
)


def _run(handler, args: list[str] | None = None) -> None:
    handler(args or [])


@app.callback()
def root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show Koza version.",
        is_eager=True,
    ),
) -> None:
    """Start Koza chat when no command is provided."""
    if version:
        cmd_version([])
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        cmd_start([])
        raise typer.Exit()


@app.command()
def google_login() -> None:
    """Google hesabina baglan (OAuth) — API anahtari olmadan Gemini kullan."""
    from providers.google_oauth_provider import cmd_google_login
    result = cmd_google_login()
    if result:
        print(result)


@app.command()
def codex_login() -> None:
    """OpenAI Codex baglantisi — API Key veya OAuth ile."""
    from providers.codex_provider import cmd_codex_login
    result = cmd_codex_login()
    if result:
        print(result)


@app.command()
def start(
    session: Optional[int] = typer.Option(None, "--session", help="Load a saved session id."),
    ui: Optional[str] = typer.Option(None, "--ui", help="UI mode: plain or tui."),
) -> None:
    """Start interactive chat."""
    args: list[str] = []
    if session is not None:
        args += ["--session", str(session)]
    if ui is not None:
        if ui not in ("plain", "tui"):
            raise typer.BadParameter("must be one of: plain, tui")
        args += ["--ui", ui]
    _run(cmd_start, args)


@app.command()
def setup() -> None:
    """Run the interactive setup wizard."""
    _run(cmd_setup)


@app.command()
def config() -> None:
    """Show current configuration with secrets masked."""
    _run(cmd_config)


@app.command()
def kanban() -> None:
    """Show Kanban board and cron jobs."""
    _run(cmd_kanban)


@app.command()
def telegram() -> None:
    """Configure Telegram bot token."""
    _run(cmd_telegram)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def logs(
    ctx: typer.Context,
    lines: int = typer.Option(100, "--lines", "-n", min=1, help="Number of log lines to show."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output."),
) -> None:
    """Show Koza daemon logs."""
    args = ["--lines", str(lines)]
    if follow or "follow" in ctx.args:
        args.append("--follow")
    _run(cmd_logs, args)


@app.command()
def status() -> None:
    """Show background service status."""
    _run(cmd_status)


@app.command()
def quit() -> None:
    """Stop Koza background services."""
    _run(cmd_quit)


@app.command("stop")
def stop_alias() -> None:
    """Alias for quit."""
    _run(cmd_quit)


@app.command()
def version() -> None:
    """Show Koza version."""
    _run(cmd_version)


@app.command()
def update() -> None:
    """Self-update Koza."""
    _run(cmd_update)


@app.command()
def uninstall() -> None:
    """Uninstall Koza local config/data."""
    _run(cmd_uninstall)


@app.command()
def clean() -> None:
    """Factory reset Koza config/data."""
    _run(cmd_clean)


@app.command()
def tui(
    session: Optional[int] = typer.Option(None, "--session", help="Load a saved session id."),
) -> None:
    """Start the Textual cockpit UI."""
    args = ["--session", str(session)] if session is not None else []
    _run(cmd_tui, args)


@app.command("help")
def help_command() -> None:
    """Show Koza command reference."""
    _run(cmd_help)


@sessions_app.callback()
def sessions_root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _run(cmd_sessions)
        raise typer.Exit()


@sessions_app.command("load")
def sessions_load(session_id: str = typer.Argument(..., help="Session id to load.")) -> None:
    """Load a saved session and start chat."""
    _run(cmd_sessions, ["load", session_id])


@sessions_app.command("delete")
def sessions_delete(session_id: str = typer.Argument(..., help="Session id to delete.")) -> None:
    """Delete a saved session."""
    _run(cmd_sessions, ["delete", session_id])


@provider_app.callback()
def provider_root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _run(cmd_provider)
        raise typer.Exit()


@provider_app.command("list")
def provider_list() -> None:
    """List configured providers."""
    _run(cmd_provider, ["list"])


@provider_app.command("use")
def provider_use(name: str = typer.Argument(..., help="Provider name or prefix.")) -> None:
    """Switch active provider."""
    _run(cmd_provider, ["use", name])


@voice_app.callback()
def voice_root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _run(cmd_voice)
        raise typer.Exit()


@voice_app.command("setup")
def voice_setup() -> None:
    """Configure Voice / STT / TTS."""
    _run(cmd_voice, ["setup"])


@voice_app.command("devices")
def voice_devices() -> None:
    """Configure audio devices."""
    _run(cmd_voice, ["devices"])


@voice_app.command("off")
def voice_off() -> None:
    """Disable voice mode."""
    _run(cmd_voice, ["off"])


@sync_app.callback()
def sync_root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _run(cmd_sync)
        raise typer.Exit()


@sync_app.command("status")
def sync_status() -> None:
    """Show sync status."""
    _run(cmd_sync, ["status"])


@sync_app.command("pull")
def sync_pull() -> None:
    """Pull latest data from master."""
    _run(cmd_sync, ["pull"])


@sync_app.command("push")
def sync_push() -> None:
    """Push local data to master."""
    _run(cmd_sync, ["push"])


@sync_app.command("now")
def sync_now() -> None:
    """Run bidirectional sync now."""
    _run(cmd_sync, ["now"])


@sync_app.command("setup")
def sync_setup() -> None:
    """Configure multi-host sync."""
    _run(cmd_sync, ["setup"])


@coding_app.callback()
def coding_root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _run(cmd_coding)
        raise typer.Exit()


@coding_app.command("status")
def coding_status() -> None:
    """Show coding session status."""
    _run(cmd_coding, ["status"])


@coding_app.command("clear")
def coding_clear() -> None:
    """Clear coding session state."""
    _run(cmd_coding, ["clear"])


app.add_typer(sessions_app, name="sessions")
app.add_typer(provider_app, name="provider")
app.add_typer(voice_app, name="voice")
app.add_typer(sync_app, name="sync")
app.add_typer(coding_app, name="coding")
