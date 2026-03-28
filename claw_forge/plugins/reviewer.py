"""Reviewer plugin — code review and quality gates.

Supports two modes:
- Standard review (default): structured checklist-based code review
- Adversarial review (--adversarial-review): GAN-inspired evaluator that
  counters the generator's optimism bias with weighted scoring dimensions
  and few-shot calibrated judgment (Anthropic harness design pattern)
"""

from __future__ import annotations

from pathlib import Path

from claw_forge.agent import collect_result
from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult


class ReviewerPlugin(BasePlugin):
    """Agent plugin for code review and quality assurance.

    When ``context.config["adversarial"]`` is True, uses the adversarial
    evaluator system prompt with weighted grading dimensions and few-shot
    calibration examples.
    """

    @property
    def name(self) -> str:
        return "reviewer"

    @property
    def description(self) -> str:
        return "Review code changes for correctness, style, security, and performance"

    def _is_adversarial(self, context: PluginContext) -> bool:
        """Check if adversarial review mode is requested."""
        return bool(context.config.get("adversarial", False))

    def get_system_prompt(self, context: PluginContext) -> str:
        if self._is_adversarial(context):
            return self._get_adversarial_prompt(context)
        return self._get_standard_prompt(context)

    def _get_standard_prompt(self, context: PluginContext) -> str:
        """Standard review system prompt."""
        return (
            "You are a senior software engineer conducting code review for claw-forge. "
            "Your reviews are structured, actionable, and fair.\n\n"
            "## Your Role\n"
            "- Review code for correctness, security, performance, and style\n"
            "- Approve PRs that meet the bar\n"
            "- Request changes with clear, specific instructions\n"
            "- Post structured reviews to the state service\n"
            "- Do NOT implement fixes yourself\n"
            "- Do NOT approve code with security vulnerabilities or missing tests\n\n"
            "## Review Checklist\n"
            "### Correctness: logic, error handling, types, async/await\n"
            "### Security: no hardcoded creds, no SQL/shell injection, input validation, "
            "no path traversal, secrets from env only\n"
            "### Performance: no N+1, async I/O, no unnecessary computation\n"
            "### Tests: ≥90% coverage, happy path, error cases, edge cases\n"
            "### Type Annotations: all params/returns annotated, no bare Any, "
            "`from __future__ import annotations`, Pydantic for complex structures\n"
            "### Style: small functions, descriptive names, no dead code, docstrings\n\n"
            "## Issue Classification\n"
            "🔴 BLOCKING: security vuln, missing tests, broken logic — must fix\n"
            "🟡 SUGGESTION: style, minor performance — should fix\n"
            "💭 NITPICK: optional naming/micro-optimization\n"
            "✅ PRAISE: reinforce good patterns\n\n"
            "## Process\n"
            "1. Run: `uv run ruff check . && uv run mypy . && uv run pytest tests/ -q`\n"
            "2. Walk the diff, apply checklist\n"
            "3. Post review to state service: "
            "POST http://localhost:8420/sessions/$SESSION_ID/events\n\n"
            "## Approval Criteria\n"
            "APPROVE: zero blocking issues, tests pass, coverage ≥90%, no security issues\n"
            "REQUEST CHANGES: any blocking issue, missing tests, coverage <90%, security vuln\n\n"
            f"Project: {context.project_path}"
        )

    def _get_adversarial_prompt(self, context: PluginContext) -> str:
        """Adversarial review system prompt with weighted grading dimensions.

        Uses the GAN-inspired evaluator pattern from Anthropic's harness
        design research: separate adversarial evaluator with explicit
        grading criteria, weighted dimensions, and few-shot calibration.
        """
        from claw_forge.harness.adversarial_evaluator import AdversarialEvaluator
        evaluator = AdversarialEvaluator()
        base_prompt = evaluator.get_system_prompt()
        return (
            f"{base_prompt}\n\n"
            "## Additional Context\n"
            "You are reviewing code in the claw-forge autonomous coding harness.\n"
            "After producing your JSON evaluation, also run:\n"
            "1. `uv run ruff check . && uv run mypy . && uv run pytest tests/ -q`\n"
            "2. Walk the diff and cite specific file:line references\n"
            "3. Post review to state service: "
            "POST http://localhost:8420/sessions/$SESSION_ID/events\n\n"
            f"Project: {context.project_path}"
        )

    def _build_prompt(self, context: PluginContext) -> str:
        return (
            f"{self.get_system_prompt(context)}\n\n"
            f"Session: {context.session_id}\n"
            f"Task ID: {context.task_id}"
        )

    async def execute(self, context: PluginContext) -> PluginResult:
        prompt = self._build_prompt(context)
        result = await collect_result(
            prompt,
            cwd=Path(context.project_path),
            allowed_tools=["Read", "Write", "Edit", "Bash"],
        )

        metadata: dict[str, object] = {
            "plugin": self.name,
            "task_id": context.task_id,
        }

        # Parse adversarial evaluation if in adversarial mode
        if self._is_adversarial(context) and result:
            from claw_forge.harness.adversarial_evaluator import AdversarialEvaluator
            evaluator = AdversarialEvaluator()
            evaluation = evaluator.parse_llm_response(result)
            metadata["adversarial_evaluation"] = evaluation.to_dict()
            metadata["adversarial_verdict"] = evaluation.verdict
            metadata["adversarial_score"] = evaluation.overall_score

        return PluginResult(
            success=True,
            output=result or "Review task completed",
            metadata=metadata,
        )
