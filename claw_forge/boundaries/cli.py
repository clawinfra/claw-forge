"""Typer subapp for ``claw-forge boundaries audit | apply | status``."""
from __future__ import annotations

from pathlib import Path

import typer

from claw_forge.boundaries.audit import run_audit
from claw_forge.boundaries.report import emit_report, parse_report

boundaries_app = typer.Typer(
    help="Plugin-boundary audit + refactor commands.",
    no_args_is_help=True,
)


@boundaries_app.command()
def audit(
    project: Path = typer.Option(
        Path.cwd(), "--project", help="Project root to audit (default: CWD)",
    ),
    min_score: float = typer.Option(
        5.0, "--min-score",
        help="Minimum hotspot score to include in the report",
    ),
    out: Path | None = typer.Option(
        None, "--out",
        help="Output path (default: <project>/boundaries_report.md)",
    ),
) -> None:
    """Read-only: scan the project, score hotspots, write boundaries_report.md."""
    project = project.resolve()
    out_path = out or (project / "boundaries_report.md")
    hotspots = run_audit(project, min_score=min_score)
    emit_report(hotspots, out_path=out_path, project_name=project.name)
    typer.echo(
        f"Wrote {out_path} with {len(hotspots)} hotspot(s) "
        f"(min score {min_score})."
    )


@boundaries_app.command()
def status(
    project: Path = typer.Option(
        Path.cwd(), "--project", help="Project root (default: CWD)",
    ),
) -> None:
    """Show the most recent audit's hotspot list."""
    report_path = project.resolve() / "boundaries_report.md"
    if not report_path.exists():
        typer.echo(
            "No boundaries_report.md — run `claw-forge boundaries audit` first."
        )
        raise typer.Exit(code=1)
    hotspots = parse_report(report_path)
    typer.echo(f"{len(hotspots)} hotspot(s) in {report_path}:")
    for h in hotspots:
        typer.echo(
            f"  {h.path:40s}  score={h.score:5.1f}  "
            f"pattern={h.pattern or '?'}"
        )
