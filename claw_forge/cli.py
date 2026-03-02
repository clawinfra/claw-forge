"""Typer CLI for claw-forge."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table

from claw_forge import __version__
from claw_forge.pool.providers.base import ProviderConfig
from claw_forge.pool.providers.registry import load_configs_from_yaml
from claw_forge.pool.manager import ProviderPoolManager
from claw_forge.pool.router import RoutingStrategy

app = typer.Typer(name="claw-forge", help="Multi-provider autonomous coding agent harness")
console = Console()


def _load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]Config not found: {path}[/red]")
        raise typer.Exit(1)
    return yaml.safe_load(path.read_text())


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
) -> None:
    """Run an agent task on a project."""
    cfg = _load_config(config)
    console.print(f"[bold]claw-forge[/bold] v{__version__}")
    console.print(f"Project: {project}")
    console.print(f"Task: {task}")
    console.print(f"Model: {model}")
    console.print(f"Providers: {len(cfg.get('providers', {}))}")
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
) -> None:
    """Initialize a project — analyze and generate manifest."""
    from claw_forge.plugins.initializer import InitializerPlugin
    from claw_forge.plugins.base import PluginContext

    plugin = InitializerPlugin()
    ctx = PluginContext(project_path=project, session_id="init", task_id="init")
    result = asyncio.run(plugin.execute(ctx))
    if result.success:
        console.print("[green]Project analyzed successfully[/green]")
        for k, v in result.metadata.items():
            console.print(f"  {k}: {v}")
    else:
        console.print(f"[red]Analysis failed: {result.output}[/red]")


if __name__ == "__main__":
    app()
