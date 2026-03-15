"""Global Safety Guard — pre-execution gate for ALL browser actions.

Unlike PolicyEngine (which evaluates post-execution in graph.py),
SafetyGuard runs BEFORE every action in ToolExecutor. This means
every execution path (graph, fast_loop, deterministic skills) gets
the same safety checks.

Checks:
  1. Sensitive page detection (login, payment, OAuth, banking URLs)
  2. Sensitive field interaction (password, credit card, SSN inputs)
  3. PII pattern detection in typed text (card numbers, SSNs)
  4. Dangerous click targets (purchase, delete, payment buttons)
  5. Sensitive fill_form batch fields (DOM hints matching sensitive patterns)

Returns SafetyVerdict:
  - ALLOW: proceed normally
  - CONFIRM: pause and show user what's about to happen
  - BLOCK: refuse to execute (e.g., typing detected credit card number)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Awaitable

logger = logging.getLogger("gaxis.safety")


# ─── VERDICT ─────────────────────────────────────────────────

class SafetyLevel(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"     # Show user, wait for approval
    BLOCK = "block"         # Refuse entirely


@dataclass
class SafetyVerdict:
    level: SafetyLevel
    reason: str
    category: str = ""      # "payment", "auth", "pii", "destructive"
    details: dict = field(default_factory=dict)


# ─── PATTERNS ────────────────────────────────────────────────

# URLs that indicate sensitive pages
SENSITIVE_URL_PATTERNS = [
    "/login", "/signin", "/sign-in", "/sign_in", "/auth",
    "/authenticate", "/log-in",
    "/checkout", "/payment", "/billing", "/pay/", "/purchase",
    "/oauth", "/authorize", "/consent", "/sso", "/saml",
    "/banking", "/bank/", "/transfer", "/wire",
    "/account/security", "/settings/password", "/2fa", "/mfa",
]

# Payment-specific URL patterns (stricter — block by default)
PAYMENT_URL_PATTERNS = [
    "/checkout", "/payment", "/billing", "/pay/", "/purchase",
    "/banking", "/bank/", "/transfer", "/wire",
    "stripe.com", "paypal.com", "venmo.com", "square.com",
]

# DOM hints that indicate sensitive fields
SENSITIVE_FIELD_HINTS = {
    "password", "passwd", "pass", "current-password", "new-password",
    "credit-card", "creditcard", "card-number", "cardnumber",
    "cvv", "cvc", "security-code", "expiry", "expiration",
    "ssn", "social-security", "tax-id", "national-id",
    "api-key", "apikey", "api_key", "secret-key", "access-token",
    "routing-number", "account-number", "bank-account",
    "sort-code", "iban", "swift",
}

# Click targets that require confirmation
DANGEROUS_CLICK_WORDS = {
    "buy", "purchase", "pay", "place order", "submit payment",
    "confirm purchase", "complete order", "checkout",
    "delete", "remove", "cancel subscription", "close account",
    "transfer", "send money", "wire",
}

# Click targets that are always safe (skip checks)
SAFE_CLICK_WORDS = {
    "save", "create", "add", "ok", "cancel", "close", "dismiss",
    "accept", "allow", "next", "back", "continue", "done",
    "search", "filter", "sort", "expand", "collapse",
}

# ─── PII REGEX PATTERNS ─────────────────────────────────────

# Credit card: 13-19 digits, optionally separated by spaces/dashes
_CC_PATTERN = re.compile(
    r"\b(?:\d[ -]*?){13,19}\b"
)

# SSN: XXX-XX-XXXX
_SSN_PATTERN = re.compile(
    r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"
)

# Email-like patterns (to detect PII being typed)
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)


def _luhn_check(digits: str) -> bool:
    """Luhn algorithm to validate credit card numbers."""
    nums = [int(d) for d in digits if d.isdigit()]
    if len(nums) < 13 or len(nums) > 19:
        return False
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ─── SAFETY GUARD ────────────────────────────────────────────

class SafetyGuard:
    """Pre-execution safety gate for all browser actions.

    Integrated into ToolExecutor.execute() — runs BEFORE the action
    is sent to the browser. Covers all execution paths.
    """

    def __init__(
        self,
        emit_fn: Callable | None = None,
        approval_fn: Callable[[], Awaitable[bool]] | None = None,
    ):
        self.emit_fn = emit_fn
        self.approval_fn = approval_fn
        # Track which sensitive pages we've already confirmed
        self._confirmed_urls: set[str] = set()
        # Count blocked actions for logging
        self._block_count = 0
        self._confirm_count = 0

    def reset(self) -> None:
        """Reset for a new task."""
        self._confirmed_urls.clear()
        self._block_count = 0
        self._confirm_count = 0

    def check(
        self,
        function_name: str,
        function_args: dict,
        current_url: str = "",
    ) -> SafetyVerdict:
        """Evaluate an action BEFORE execution.

        Returns SafetyVerdict indicating whether to proceed.
        """
        # Control-flow tools are always safe
        if function_name in (
            "task_complete", "task_failed", "task_partial",
            "delegate", "extract_data", "plan_task", "confirm_action",
            "wait", "scroll", "hover",
        ):
            return SafetyVerdict(SafetyLevel.ALLOW, "Safe action")

        # ── Check 1: Current page sensitivity ──
        if current_url:
            page_verdict = self._check_page(current_url, function_name)
            if page_verdict.level != SafetyLevel.ALLOW:
                return page_verdict

        # ── Check 2: Navigation target ──
        if function_name == "navigate":
            return self._check_navigate(function_args)

        # ── Check 3: Text input ──
        if function_name == "type_text":
            return self._check_type_text(function_args)

        # ── Check 4: Click targets ──
        if function_name == "click":
            return self._check_click(function_args)

        # ── Check 5: Batch form fill ──
        if function_name == "fill_form":
            return self._check_fill_form(function_args)

        # ── Check 6: Key presses ──
        if function_name == "press_key":
            return self._check_press_key(function_args, current_url)

        return SafetyVerdict(SafetyLevel.ALLOW, "No safety concerns")

    # ── Individual checks ──────────────────────────────────

    def _check_page(self, url: str, action: str) -> SafetyVerdict:
        """Check if we're on a sensitive page."""
        url_lower = url.lower()

        # Payment pages — block all typing/clicking unless confirmed
        if action in ("type_text", "click", "fill_form"):
            for pattern in PAYMENT_URL_PATTERNS:
                if pattern in url_lower:
                    if url not in self._confirmed_urls:
                        return SafetyVerdict(
                            SafetyLevel.CONFIRM,
                            f"Action on payment page (URL contains '{pattern}'). "
                            f"Confirm before proceeding.",
                            category="payment",
                            details={"url": url, "pattern": pattern},
                        )

        # Auth pages — confirm form interactions
        if action in ("type_text", "fill_form"):
            auth_patterns = ["/login", "/signin", "/sign-in", "/auth", "/authenticate"]
            for pattern in auth_patterns:
                if pattern in url_lower:
                    if url not in self._confirmed_urls:
                        return SafetyVerdict(
                            SafetyLevel.CONFIRM,
                            f"Typing on login/auth page (URL contains '{pattern}'). "
                            f"Confirm this is intended.",
                            category="auth",
                            details={"url": url, "pattern": pattern},
                        )

        return SafetyVerdict(SafetyLevel.ALLOW, "Page OK")

    def _check_navigate(self, args: dict) -> SafetyVerdict:
        """Check navigation targets."""
        url = (args.get("url", "") or "").lower()

        for pattern in PAYMENT_URL_PATTERNS:
            if pattern in url:
                return SafetyVerdict(
                    SafetyLevel.CONFIRM,
                    f"Navigating to payment/banking page: '{pattern}' in URL.",
                    category="payment",
                    details={"url": url, "pattern": pattern},
                )

        return SafetyVerdict(SafetyLevel.ALLOW, "Navigation OK")

    def _check_type_text(self, args: dict) -> SafetyVerdict:
        """Check text being typed for PII or sensitive field targets."""
        text = args.get("text", "")
        element_desc = (args.get("element_description", "") or "").lower()

        # Check if typing into a sensitive field
        for hint in SENSITIVE_FIELD_HINTS:
            if hint in element_desc:
                return SafetyVerdict(
                    SafetyLevel.CONFIRM,
                    f"Typing into sensitive field: '{hint}' detected in element description.",
                    category="auth" if "password" in hint or "pass" in hint else "pii",
                    details={"field": hint, "element": element_desc},
                )

        # Check typed text for PII patterns
        pii_verdict = self._check_text_for_pii(text)
        if pii_verdict.level != SafetyLevel.ALLOW:
            return pii_verdict

        return SafetyVerdict(SafetyLevel.ALLOW, "Text input OK")

    def _check_text_for_pii(self, text: str) -> SafetyVerdict:
        """Scan text for credit card numbers, SSNs, etc."""
        if not text or len(text) < 9:
            return SafetyVerdict(SafetyLevel.ALLOW, "Text too short for PII")

        # Credit card number detection
        cc_matches = _CC_PATTERN.findall(text)
        for match in cc_matches:
            digits = re.sub(r"[^\d]", "", match)
            if _luhn_check(digits):
                return SafetyVerdict(
                    SafetyLevel.BLOCK,
                    "Credit card number detected in typed text. "
                    "Refusing to type financial data automatically.",
                    category="payment",
                    details={"pattern": "credit_card", "length": len(digits)},
                )

        # SSN detection
        if _SSN_PATTERN.search(text):
            # Extra check: not a phone number or date
            candidate = re.sub(r"[^\d]", "", _SSN_PATTERN.search(text).group())
            # SSNs don't start with 000, 666, or 9xx
            if not candidate.startswith(("000", "666")) and not candidate[0] == "9":
                return SafetyVerdict(
                    SafetyLevel.BLOCK,
                    "Possible SSN detected in typed text. "
                    "Refusing to type government ID data automatically.",
                    category="pii",
                    details={"pattern": "ssn"},
                )

        return SafetyVerdict(SafetyLevel.ALLOW, "No PII detected")

    def _check_click(self, args: dict) -> SafetyVerdict:
        """Check click targets for dangerous actions."""
        desc = (args.get("element_description", "") or "").lower()

        if not desc:
            return SafetyVerdict(SafetyLevel.ALLOW, "No description")

        # Skip check for known-safe targets
        for safe in SAFE_CLICK_WORDS:
            if safe in desc:
                return SafetyVerdict(SafetyLevel.ALLOW, f"Safe click: '{safe}'")

        # Check for dangerous targets
        for danger in DANGEROUS_CLICK_WORDS:
            if danger in desc:
                return SafetyVerdict(
                    SafetyLevel.CONFIRM,
                    f"Clicking potentially dangerous element: '{danger}' in '{desc[:60]}'.",
                    category="destructive" if danger in ("delete", "remove", "cancel subscription", "close account") else "payment",
                    details={"target": desc, "matched": danger},
                )

        return SafetyVerdict(SafetyLevel.ALLOW, "Click OK")

    def _check_fill_form(self, args: dict) -> SafetyVerdict:
        """Check batch form fill for sensitive fields."""
        fields = args.get("fields", [])

        for i, f in enumerate(fields):
            hints = f.get("hints", {})
            value = f.get("value", "")

            # Check field hints against sensitive patterns
            all_hints = " ".join([
                hints.get("placeholder", ""),
                hints.get("aria", ""),
                hints.get("text", ""),
            ]).lower()

            for sensitive in SENSITIVE_FIELD_HINTS:
                if sensitive in all_hints:
                    return SafetyVerdict(
                        SafetyLevel.CONFIRM,
                        f"Batch fill targets sensitive field: '{sensitive}' "
                        f"in field {i} hints.",
                        category="auth" if "password" in sensitive or "pass" in sensitive else "pii",
                        details={"field_index": i, "hint": sensitive, "all_hints": all_hints},
                    )

            # Check values for PII
            if value:
                pii_verdict = self._check_text_for_pii(value)
                if pii_verdict.level != SafetyLevel.ALLOW:
                    return pii_verdict

        return SafetyVerdict(SafetyLevel.ALLOW, "Form fill OK")

    def _check_press_key(self, args: dict, current_url: str) -> SafetyVerdict:
        """Check key presses on sensitive pages."""
        key = (args.get("key", "") or "").lower()

        # Enter on payment pages could submit payment
        if key == "enter" and current_url:
            url_lower = current_url.lower()
            for pattern in PAYMENT_URL_PATTERNS:
                if pattern in url_lower:
                    return SafetyVerdict(
                        SafetyLevel.CONFIRM,
                        f"Pressing Enter on payment page could submit payment.",
                        category="payment",
                        details={"key": key, "url": current_url},
                    )

        return SafetyVerdict(SafetyLevel.ALLOW, "Key press OK")

    # ── Approval tracking ──────────────────────────────────

    def mark_url_confirmed(self, url: str) -> None:
        """Mark a URL as user-confirmed (skip future checks for this page)."""
        self._confirmed_urls.add(url)

    @property
    def stats(self) -> dict:
        return {
            "blocked": self._block_count,
            "confirmed": self._confirm_count,
            "confirmed_urls": len(self._confirmed_urls),
        }
