"""End-to-end tests: explicit ``<feature depends_on>`` edges in a spec become
``Task.depends_on`` UUID lists in the state DB and produce correct execution
order from the runtime scheduler.

The conversion pipeline is:
1. parser.py reads ``<feature depends_on="N">`` and resolves N (1-based feature
   index) to a 0-based position.
2. ``initializer.py`` emits ``{"index": pos, "depends_on_indices": [pos, ...]}``.
3. ``cli._write_plan_to_db`` builds an ``index → uuid`` map and translates the
   positional indices into UUID lists for ``Task.depends_on``.
4. ``Scheduler.get_execution_order`` honors the UUID edges and produces correct
   wave ordering.
"""
from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from claw_forge.cli import _write_plan_to_db
from claw_forge.spec.parser import ProjectSpec
from claw_forge.state.scheduler import Scheduler, TaskNode


def _features_payload_from_spec(spec: ProjectSpec) -> list[dict[str, object]]:
    """Replicate ``initializer.py``'s FeatureItem → dict conversion."""
    return [
        {
            "index": i,
            "category": feat.category,
            "name": feat.name,
            "description": feat.description,
            "steps": feat.steps,
            "depends_on_indices": feat.depends_on_indices,
        }
        for i, feat in enumerate(spec.features)
    ]


@pytest.fixture()
def explicit_edges_xml() -> str:
    return textwrap.dedent("""
        <project_specification>
          <project_name>EdgeTest</project_name>
          <core_features>
            <category name="X">
              <feature index="1"><description>A first</description></feature>
              <feature index="2" depends_on="1"><description>B depends on A</description></feature>
            </category>
          </core_features>
        </project_specification>
    """).strip()


def test_explicit_edges_become_task_depends_on_uuids(
    tmp_path: Path, explicit_edges_xml: str,
) -> None:
    """End-to-end: explicit ``<feature depends_on>`` produces matching
    ``Task.depends_on`` UUID lists in state.db."""
    spec = ProjectSpec._parse_xml(explicit_edges_xml)
    features = _features_payload_from_spec(spec)
    asyncio.run(_write_plan_to_db(
        tmp_path, "EdgeTest", features, fresh=True,
    ))

    # Read tasks back from the DB
    import sqlite3
    db_path = tmp_path / ".claw-forge" / "state.db"
    assert db_path.exists()
    con = sqlite3.connect(str(db_path))
    cur = con.execute("SELECT id, description, depends_on FROM tasks ORDER BY priority")
    rows = cur.fetchall()
    con.close()

    assert len(rows) == 2
    a_id, a_desc, a_deps = rows[0]
    _b_id, b_desc, b_deps = rows[1]
    assert "A first" in a_desc
    assert "B depends on A" in b_desc
    # A has no deps; B's deps include A's UUID.
    import json
    a_deps_list = json.loads(a_deps) if a_deps else []
    b_deps_list = json.loads(b_deps) if b_deps else []
    assert a_deps_list == []
    assert b_deps_list == [a_id], (
        f"Expected B to depend on A's id; got {b_deps_list!r}"
    )


def test_scheduler_places_dependent_feature_in_later_wave(
    tmp_path: Path, explicit_edges_xml: str,
) -> None:
    """Feeding the resulting tasks into the runtime scheduler produces 2 waves:
    the independent feature first, the dependent one second."""
    spec = ProjectSpec._parse_xml(explicit_edges_xml)
    features = _features_payload_from_spec(spec)
    asyncio.run(_write_plan_to_db(
        tmp_path, "EdgeTest", features, fresh=True,
    ))

    # Hydrate the DB rows into TaskNodes
    import json
    import sqlite3
    db_path = tmp_path / ".claw-forge" / "state.db"
    con = sqlite3.connect(str(db_path))
    cur = con.execute(
        "SELECT id, plugin_name, priority, depends_on FROM tasks ORDER BY priority"
    )
    nodes: list[TaskNode] = []
    for tid, plugin, priority, deps_json in cur.fetchall():
        deps = json.loads(deps_json) if deps_json else []
        nodes.append(TaskNode(
            id=tid, plugin_name=plugin or "coding",
            priority=priority or 0, depends_on=deps,
        ))
    con.close()

    sched = Scheduler()
    for n in nodes:
        sched.add_task(n)
    waves = sched.get_execution_order()
    assert len(waves) == 2, f"expected 2 waves, got {len(waves)}: {waves}"
    # Wave 1 is the independent feature; wave 2 is the dependent one.
    a_id = nodes[0].id
    b_id = nodes[1].id
    assert waves[0] == [a_id]
    assert waves[1] == [b_id]
