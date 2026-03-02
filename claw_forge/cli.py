"""Typer CLI for claw-forge."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
import typer
import yaml
from rich.console import Console
from rich.table import Table

from claw_forge import __version__
from claw_forge.pool.providers.registry import load_configs_from_yaml
from claw_forge.pool.router import RoutingStrategy

app = typer.Typer(name="claw-forge", help="Multi-provider autonomous coding agent harness")
console = Console()

# ── Helpers ──────────────────────────────────────────────────────────────────


def _load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]Config not found: {path}[/red]")
        raise typer.Exit(1)
    return yaml.safe_load(path.read_text())


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
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]HTTP {exc.response.status_code}: {exc.response.text}[/red]")
        raise typer.Exit(1)


def _http_post(url: str, json: dict | None = None) -> dict:
    """Simple synchronous POST helper."""
    try:
        resp = httpx.post(url, json=json or {}, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print(f"[red]State service not reachable at {url}[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]HTTP {exc.response.status_code}: {exc.response.text}[/red]")
        raise typer.Exit(1)


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
    yolo: bool = typer.Option(False, "--yolo", help="Skip human input, max concurrency, aggressive retry"),
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
            f"[bold yellow]⚠️  YOLO MODE: Human approval skipped, max concurrency ({cpu_count}), aggressive retry[/bold yellow]"
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
    spec: Optional[str] = typer.Option(None, "--spec", "-s", help="Path to app_spec.txt"),
) -> None:
    """Initialize a project — analyze and generate manifest."""
    from claw_forge.plugins.initializer import InitializerPlugin
    from claw_forge.plugins.base import PluginContext

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
        raise typer.Exit(1)


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
        raise typer.Exit(1)


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

    console.print(f"[bold yellow]🙋 {len(pending)} pending question(s) for {project!r}:[/bold yellow]\n")

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


if __name__ == "__main__":
    app()
