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

# URL patterns indicating sensitive pages (login, payment, OAuth, banking)
SENSITIVE_URL_PATTERNS = [
    "/login", "/signin", "/sign-in", "/sign_in", "/auth",
    "/authenticate", "/log-in",
    "/checkout", "/payment", "/billing", "/pay", "/purchase",
    "/oauth", "/authorize", "/consent", "/sso", "/saml",
    "/banking", "/bank", "/transfer", "/wire",
    "/account/security", "/settings/password", "/2fa", "/mfa",
]

# Form field names/IDs/labels that indicate sensitive data
SENSITIVE_FIELD_NAMES = [
    "password", "passwd", "pass", "current-password", "new-password",
    "credit-card", "creditcard", "card-number", "cardnumber",
    "cvv", "cvc", "security-code", "expiry", "expiration",
    "ssn", "social-security", "tax-id", "national-id",
    "api-key", "apikey", "api_key", "secret-key", "access-token",
    "routing-number", "account-number", "bank-account",
    "sort-code", "iban", "swift",
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
        url: str | None = None,
    ) -> PolicyDecision:
        # Low confidence always requires approval
        if confidence < self.confidence_threshold:
            return PolicyDecision(
                verdict="require_approval",
                risk_level="high",
                reason=f"Confidence ({confidence:.0%}) below threshold ({self.confidence_threshold:.0%})",
            )

        # Sensitive page detection — login, payment, OAuth, banking
        if url:
            url_lower = url.lower()
            for pattern in SENSITIVE_URL_PATTERNS:
                if pattern in url_lower:
                    return PolicyDecision(
                        verdict="require_approval",
                        risk_level="critical",
                        reason=f"Sensitive page detected: URL contains '{pattern}' — requires explicit approval",
                    )

        # Sensitive elements always require approval
        if is_sensitive:
            return PolicyDecision(
                verdict="require_approval",
                risk_level="critical",
                reason="Target element contains sensitive data (password/payment)",
            )

        # Check element_id against expanded sensitive field names
        if element_id:
            eid = element_id.lower()
            for kw in SENSITIVE_FIELD_NAMES:
                if kw in eid:
                    return PolicyDecision(
                        verdict="require_approval",
                        risk_level="critical",
                        reason=f"Sensitive form field detected: '{element_id}' — pausing for user confirmation",
                    )
            # Legacy: also check original keywords
            if any(kw in eid for kw in SENSITIVE_KEYWORDS):
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
            case "type" | "type_text" | "select_all_and_type":
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
