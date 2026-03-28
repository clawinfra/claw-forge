"""Harness improvements — context resets, adversarial evaluation, pivot decisions.

Inspired by Anthropic's engineering blog posts on harness design for
long-running applications and effective context engineering.
"""

from .context_reset import ContextResetManager, HandoffArtifact
from .adversarial_evaluator import AdversarialEvaluator, EvaluationResult, GradingDimension
from .pivot_decision import PivotDecision, PivotTracker

__all__ = [
    "ContextResetManager",
    "HandoffArtifact",
    "AdversarialEvaluator",
    "EvaluationResult",
    "GradingDimension",
    "PivotDecision",
    "PivotTracker",
]
