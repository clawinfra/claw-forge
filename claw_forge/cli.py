"""Typer CLI for claw-forge."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
import typer
import yaml
from rich.console import Console
from rich.table import Table

from claw_forge import __version__
from claw_forge.pool.providers.registry import load_configs_from_yaml

app = typer.Typer(name="claw-forge", help="Multi-provider autonomous coding agent harness")
console = Console()

# ── Helpers ──────────────────────────────────────────────────────────────────


def _expand_env_vars(obj: object) -> object:
    """Recursively expand ${VAR} placeholders using os.environ."""
    import re
    if isinstance(obj, str):
        def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
            key = m.group(1)
            val = os.environ.get(key, "")
            if not val:
                console.print(f"[yellow]⚠ Env var ${{{key}}} is not set[/yellow]")
            return val
        return re.sub(r"\$\{([^}]+)\}", _replace, obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(i) for i in obj]
    return obj


def _load_config(config_path: str) -> dict:
    """Load YAML config and expand ${ENV_VAR} placeholders from environment."""
    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]Config not found: {path}[/red]")
        raise typer.Exit(1) from None
    # Auto-load .env file if present alongside the config
    env_file = path.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())
    raw = yaml.safe_load(path.read_text())
    return _expand_env_vars(raw)  # type: ignore[return-value]


def _state_url(port: int = 8420) -> str:
    return f"http://localhost:{port}"


def _http_get(url: str) -> dict | list:
    """Simple synchronous GET helper."""
    try:
        resp = httpx.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print(f"[red]State service not reachable at {url}[/red]")
        raise typer.Exit(1) from None
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]HTTP {exc.response.status_code}: {exc.response.text}[/red]")
        raise typer.Exit(1) from None


def _http_post(url: str, json: dict | None = None) -> dict:
    """Simple synchronous POST helper."""
    try:
        resp = httpx.post(url, json=json or {}, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print(f"[red]State service not reachable at {url}[/red]")
        raise typer.Exit(1) from None
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]HTTP {exc.response.status_code}: {exc.response.text}[/red]")
        raise typer.Exit(1) from None


# ── Commands ──────────────────────────────────────────────────────────────────


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"claw-forge {__version__}")


@app.command()
def run(
    config: str = typer.Option("claw-forge.yaml", "--config", "-c"),
    project: str = typer.Option(".", "--project", "-p"),
    task: str = typer.Option("coding", "--task", "-t"),
    model: str = typer.Option("claude-sonnet-4-20250514", "--model", "-m"),
    concurrency: int = typer.Option(5, "--concurrency", "-n", help="Max parallel agents"),
    yolo: bool = typer.Option(False, "--yolo", help="Skip human input, max concurrency, aggressive retry"),  # noqa: E501
) -> None:
    """Run an agent task on a project."""
    cfg = _load_config(config)
    console.print(f"[bold]claw-forge[/bold] v{__version__}")
    console.print(f"Project: {project}")
    console.print(f"Task: {task}")
    console.print(f"Model: {model}")
    console.print(f"Providers: {len(cfg.get('providers', {}))}")

    if yolo:
        cpu_count = max(1, os.cpu_count() or 4)
        console.print(
            f"[bold yellow]⚠️  YOLO MODE: Human approval skipped, max concurrency ({cpu_count}), aggressive retry[/bold yellow]"  # noqa: E501
        )

    console.print("[yellow]Agent loop not yet integrated — scaffold only[/yellow]")


@app.command()
def pool_status(
    config: str = typer.Option("claw-forge.yaml", "--config", "-c"),
) -> None:
    """Show provider pool status."""
    cfg = _load_config(config)
    configs = load_configs_from_yaml(cfg)

    table = Table(title="Provider Pool")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Priority")
    table.add_column("Enabled")
    table.add_column("Cost (in/out $/Mtok)")

    for c in configs:
        table.add_row(
            c.name,
            c.provider_type.value,
            str(c.priority),
            "✅" if c.enabled else "❌",
            f"${c.cost_per_mtok_input}/{c.cost_per_mtok_output}",
        )
    console.print(table)


@app.command()
def state(
    port: int = typer.Option(8420, "--port"),
    host: str = typer.Option("0.0.0.0", "--host"),
) -> None:
    """Start the AgentStateService REST API."""
    import uvicorn

    from claw_forge.state.service import AgentStateService

    svc = AgentStateService()
    uvicorn.run(svc.create_app(), host=host, port=port)


@app.command()
def init(
    project: str = typer.Option(".", "--project", "-p"),
    spec: str | None = typer.Option(None, "--spec", "-s", help="Path to app_spec.txt"),
) -> None:
    """Initialize a project — analyze and generate manifest."""
    from claw_forge.plugins.base import PluginContext
    from claw_forge.plugins.initializer import InitializerPlugin

    plugin = InitializerPlugin()
    ctx = PluginContext(project_path=project, session_id="init", task_id="init")
    if spec:
        ctx.metadata = {"spec_file": spec}
    result = asyncio.run(plugin.execute(ctx))
    if result.success:
        console.print("[green]Project analyzed successfully[/green]")
        for k, v in result.metadata.items():
            console.print(f"  {k}: {v}")
    else:
        console.print(f"[red]Analysis failed: {result.output}[/red]")


@app.command()
def pause(
    project: str = typer.Argument(..., help="Session ID or project name to pause"),
    port: int = typer.Option(8420, "--port", help="State service port"),
) -> None:
    """Pause a running project (drain mode: finish in-flight agents, start no new ones)."""
    url = f"{_state_url(port)}/project/pause?session_id={project}"
    result = _http_post(url)
    paused = result.get("paused", False)
    if paused:
        console.print(f"[yellow]⏸  Project {project!r} paused.[/yellow]")
        console.print("In-flight agents will complete. No new agents will start.")
        console.print(f"Resume with: [bold]claw-forge resume {project}[/bold]")
    else:
        console.print(f"[red]Unexpected response: {result}[/red]")
        raise typer.Exit(1) from None


@app.command()
def resume(
    project: str = typer.Argument(..., help="Session ID or project name to resume"),
    port: int = typer.Option(8420, "--port", help="State service port"),
) -> None:
    """Resume a paused project — dispatcher starts accepting new tasks again."""
    url = f"{_state_url(port)}/project/resume?session_id={project}"
    result = _http_post(url)
    paused = result.get("paused", True)
    if not paused:
        console.print(f"[green]▶  Project {project!r} resumed.[/green]")
        console.print("Dispatcher is now accepting new tasks.")
    else:
        console.print(f"[red]Unexpected response: {result}[/red]")
        raise typer.Exit(1) from None


@app.command(name="input")
def human_input(
    project: str = typer.Argument(..., help="Session ID or project name"),
    port: int = typer.Option(8420, "--port", help="State service port"),
) -> None:
    """List pending human-input questions and answer them interactively.

    Agents that are stuck POST a question to /features/{id}/human-input.
    This command shows those questions and submits your answers, moving
    the feature back to 'pending' for the dispatcher to retry.
    """
    url = f"{_state_url(port)}/features/needs-human?session_id={project}"
    pending: list[dict] = _http_get(url)  # type: ignore[assignment]

    if not pending:
        console.print(f"[green]✅ No pending human-input questions for {project!r}[/green]")
        return

    console.print(f"[bold yellow]🙋 {len(pending)} pending question(s) for {project!r}:[/bold yellow]\n")  # noqa: E501

    for item in pending:
        task_id = item["task_id"]
        question = item.get("question", "(no question text)")
        description = item.get("description", "")

        console.print(f"[bold]Task:[/bold] {description or task_id}")
        console.print(f"[bold yellow]Q:[/bold yellow] {question}")
        answer = typer.prompt("Your answer")

        answer_url = f"{_state_url(port)}/features/{task_id}/human-answer"
        _http_post(answer_url, json={"answer": answer})
        console.print(f"[green]✅ Answer submitted — task {task_id} moved to pending[/green]\n")

    console.print(f"[green]All questions answered. Project {project!r} can now continue.[/green]")


@app.command()
def ui(
    port: int = typer.Option(
        int(os.environ.get("CLAW_FORGE_UI_PORT", "5173")),
        "--port",
        "-p",
        help="Port for the Kanban UI dev server",
    ),
    state_port: int = typer.Option(  # noqa: E501
        8888, "--state-port", help="Port the state service is running on"
    ),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser automatically"),
    session: str = typer.Option("", "--session", "-s", help="Session UUID to open on the board"),
) -> None:
    """Launch the Kanban UI (React dev server).

    Requires Node.js and the UI dependencies installed:

        cd ui && npm install

    Starts the Vite dev server and optionally opens the board in your browser.
    The UI connects to the state service at localhost:<state-port>.
    """
    import shutil
    import subprocess

    ui_dir = Path(__file__).parent.parent / "ui"
    if not ui_dir.exists():
        console.print("[red]ui/ directory not found. Is claw-forge installed from source?[/red]")
        raise typer.Exit(1) from None

    if not shutil.which("node"):
        console.print("[red]Node.js not found. Install it from https://nodejs.org/[/red]")
        raise typer.Exit(1) from None

    node_modules = ui_dir / "node_modules"
    if not node_modules.exists():
        console.print("[yellow]Installing UI dependencies (npm install)…[/yellow]")
        subprocess.run(["npm", "install"], cwd=ui_dir, check=True)  # noqa: S603, S607

    url = f"http://localhost:{port}"
    if session:
        url += f"/?session={session}"

    console.print("[bold green]🔥 Starting claw-forge Kanban UI[/bold green]")
    console.print(f"   UI:           [cyan]{url}[/cyan]")
    console.print(f"   State API:    [cyan]http://localhost:{state_port}[/cyan]")
    console.print("   Press [bold]Ctrl+C[/bold] to stop\n")

    env = os.environ.copy()
    env["VITE_API_PORT"] = str(state_port)
    env["VITE_WS_PORT"] = str(state_port)

    if open_browser:
        import threading
        import time
        import webbrowser

        def _open_after_delay() -> None:
            time.sleep(2)  # wait for Vite to start
            webbrowser.open(url)

        threading.Thread(target=_open_after_delay, daemon=True).start()

    subprocess.run(  # noqa: S603, S607
        ["npm", "run", "dev", "--", "--port", str(port), "--host"],
        cwd=ui_dir,
        env=env,
        check=False,
    )


if __name__ == "__main__":
    app()
