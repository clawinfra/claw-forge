"""Typer subapp for ``claw-forge boundaries audit | apply | status``."""
from __future__ import annotations

from pathlib import Path

import typer

from claw_forge.boundaries.apply import apply_hotspot
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
def apply(
    project: Path = typer.Option(
        Path.cwd(), "--project", help="Project root (default: CWD)",
    ),
    test_command: str = typer.Option(
        "uv run pytest tests/ -q",
        "--test-command",
        help="Test command (run inside each refactor's worktree)",
    ),
    hotspot: str | None = typer.Option(
        None, "--hotspot",
        help="Apply only this one hotspot (relative path from project root)",
    ),
    auto: bool = typer.Option(
        False, "--auto",
        help="No prompts; apply all hotspots in score order",
    ),
) -> None:
    """Apply hotspot refactors from boundaries_report.md, gated by tests.

    If no report exists, runs ``audit`` first with the default min-score.
    Each hotspot is processed serially: subagent edits → tests → merge/revert.
    """
    project = project.resolve()
    report_path = project / "boundaries_report.md"
    if not report_path.exists():
        typer.echo(
            "No boundaries_report.md — running audit first…"
        )
        spots = run_audit(project)
        emit_report(spots, out_path=report_path, project_name=project.name)

    hotspots = parse_report(report_path)
    if hotspot:
        hotspots = [h for h in hotspots if h.path == hotspot]
        if not hotspots:
            typer.echo(f"No hotspot named {hotspot!r} in report.")
            raise typer.Exit(code=1)

    n_merged = n_reverted = n_skipped = 0
    for h in hotspots:
        if not auto:
            typer.echo(
                f"\nNext: {h.path} (score {h.score:.1f}, "
                f"pattern={h.pattern or '?'})"
            )
            if not typer.confirm("Apply?", default=False):
                n_skipped += 1
                continue
        result = apply_hotspot(
            h, project_dir=project, test_command=test_command,
        )
        status_str = result["status"]
        if status_str == "merged":
            n_merged += 1
        elif status_str == "reverted":
            n_reverted += 1
        else:
            n_skipped += 1
        typer.echo(
            f"  {h.path}: {status_str} ({result.get('reason', '')})"
        )
    typer.echo(
        f"\nDone. {n_merged} merged, {n_reverted} reverted, "
        f"{n_skipped} skipped."
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
