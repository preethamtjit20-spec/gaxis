"""Policy engine for G-Axis.

Evaluates planned actions against risk rules and decides whether
to auto-allow, require operator approval, or deny.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PolicyVerdict = Literal["allow", "require_approval", "deny"]


@dataclass
class PolicyDecision:
    verdict: PolicyVerdict
    risk_level: str
    reason: str


RISK_WEIGHT = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

SENSITIVE_KEYWORDS = [
    "password", "passwd", "secret", "pin", "ssn", "credit-card",
    "cvv", "cvc", "security-code", "card-number", "payment",
]


class PolicyEngine:
    """Rule-based policy engine with cumulative risk tracking."""

    def __init__(self, confidence_threshold: float = 0.4, cumulative_risk_limit: int = 60):
        self.confidence_threshold = confidence_threshold
        self.cumulative_risk_limit = cumulative_risk_limit
        self.cumulative_risk = 0
        self.approval_history: list[str] = []

    def reset(self) -> None:
        self.cumulative_risk = 0
        self.approval_history = []

    def evaluate(
        self,
        action_type: str,
        risk_level: str,
        confidence: float,
        element_id: str | None = None,
        is_sensitive: bool = False,
    ) -> PolicyDecision:
        # Low confidence always requires approval
        if confidence < self.confidence_threshold:
            return PolicyDecision(
                verdict="require_approval",
                risk_level="high",
                reason=f"Confidence ({confidence:.0%}) below threshold ({self.confidence_threshold:.0%})",
            )

        # Sensitive elements always require approval
        if is_sensitive:
            return PolicyDecision(
                verdict="require_approval",
                risk_level="critical",
                reason="Target element contains sensitive data (password/payment)",
            )

        # Check element_id for sensitive keywords
        if element_id and any(kw in element_id.lower() for kw in SENSITIVE_KEYWORDS):
            return PolicyDecision(
                verdict="require_approval",
                risk_level="high",
                reason=f"Element '{element_id}' matches sensitive keyword pattern",
            )

        # Base risk from action type
        base = self._base_risk(action_type, risk_level)

        # Cumulative risk escalation
        risk_weight = RISK_WEIGHT.get(risk_level, 2)
        self.cumulative_risk += risk_weight

        if self.cumulative_risk > self.cumulative_risk_limit and risk_weight >= 2:
            return PolicyDecision(
                verdict="require_approval",
                risk_level=risk_level,
                reason=f"Cumulative risk ({self.cumulative_risk}) exceeds limit ({self.cumulative_risk_limit})",
            )

        return base

    def record_approval(self, action_type: str) -> None:
        self.approval_history.append(action_type)

    def _base_risk(self, action_type: str, risk_level: str) -> PolicyDecision:
        match action_type:
            case "scroll" | "wait" | "done":
                return PolicyDecision("allow", "none", "Passive action")
            case "click":
                if RISK_WEIGHT.get(risk_level, 0) >= 3:
                    return PolicyDecision(
                        "require_approval", risk_level,
                        "Click on high-risk element"
                    )
                return PolicyDecision("allow", risk_level, "Click interaction")
            case "type" | "select_all_and_type":
                if RISK_WEIGHT.get(risk_level, 0) >= 3:
                    return PolicyDecision(
                        "require_approval", risk_level,
                        "Text input into high-risk field"
                    )
                return PolicyDecision("allow", risk_level, "Text input")
            case "navigate":
                return PolicyDecision("allow", "medium", "Navigation")
            case "press_key":
                return PolicyDecision("allow", "low", "Keyboard input")
            case _:
                return PolicyDecision("require_approval", "medium", f"Unknown action: {action_type}")
