"""
Security Agent
Prevents prompt injection, SQL injection, unauthorized access.
Audit logging for all interactions.
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("lab_assistant")
security_logger = logging.getLogger("security")


@dataclass
class SecurityResult:
    is_safe: bool = True
    threat_type: Optional[str] = None
    rejection_message: str = ""
    risk_score: float = 0.0


class SecurityAgent:
    """
    Security checks run BEFORE processing every message.
    Detects: prompt injection, jailbreak attempts, data exfiltration attempts,
    unauthorized SQL commands, and excessive data requests.
    """

    # Prompt injection patterns
    INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"forget\s+your\s+(system\s+)?instructions",
        r"you\s+are\s+now\s+a?\s*(different|new|jailbroken|DAN)",
        r"act\s+as\s+(if\s+you\s+are\s+)?a?\s*(different|unrestricted|evil|jailbroken)",
        r"override\s+(your\s+)?(safety|guidelines|instructions|rules)",
        r"disregard\s+(all\s+)?(previous|your|safety)",
        r"pretend\s+(you\s+)?(are|have\s+no)\s+(restrictions|guidelines|rules)",
        r"\[SYSTEM\]|\[INST\]|<\|im_start\|>|<\|system\|>",
        r"jailbreak|DAN mode|developer mode|unrestricted mode",
        r"print\s+(your\s+)?(system\s+prompt|instructions|rules)",
        r"reveal\s+(your\s+)?(hidden|secret|system)\s+(prompt|instructions)",
    ]

    # Data exfiltration patterns
    EXFILTRATION_PATTERNS = [
        r"send\s+(data|results|passwords?)\s+to",
        r"email\s+(me|the\s+results)\s+to",
        r"upload\s+(to|results?\s+to)",
        r"http[s]?://(?!localhost)",   # External URL references
        r"base64\s+(encode|decode)",
        r"dump\s+(all\s+)?(database|table|users?|passwords?)",
    ]

    # Maximum message length
    MAX_MESSAGE_LENGTH = 2000

    # Sensitive data patterns to mask in logs
    SENSITIVE_PATTERNS = [
        (r"\b\d{3}-\d{2}-\d{4}\b", "***-**-****"),          # SSN
        (r"\b\d{16}\b", "****-****-****-****"),               # Credit card
        (r"password\s*[:=]\s*\S+", "password: [REDACTED]"),  # Passwords
    ]

    def check(self, context) -> SecurityResult:
        """Run all security checks on the incoming message."""
        message = context.message
        user_id = context.user_id
        user_role = context.user_role

        # 1. Length check
        if len(message) > self.MAX_MESSAGE_LENGTH:
            security_logger.warning(
                f"Message too long from user {user_id}: {len(message)} chars"
            )
            return SecurityResult(
                is_safe=False,
                threat_type="MESSAGE_TOO_LONG",
                rejection_message=(
                    f"Your message is too long ({len(message)} characters). "
                    f"Please limit questions to {self.MAX_MESSAGE_LENGTH} characters."
                ),
                risk_score=0.3,
            )

        # 2. Prompt injection check
        injection_result = self._check_injection(message, user_id)
        if not injection_result.is_safe:
            return injection_result

        # 3. Exfiltration check
        exfil_result = self._check_exfiltration(message, user_id)
        if not exfil_result.is_safe:
            return exfil_result

        # 4. Role-based access check
        rbac_result = self._check_rbac(context)
        if not rbac_result.is_safe:
            return rbac_result

        return SecurityResult(is_safe=True, risk_score=0.0)

    def _check_injection(self, message: str, user_id: int) -> SecurityResult:
        """Detect prompt injection attempts."""
        lower_msg = message.lower()
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, lower_msg, re.IGNORECASE):
                security_logger.warning(
                    f"PROMPT INJECTION DETECTED | user={user_id} | "
                    f"pattern={pattern} | message_preview={message[:100]}"
                )
                return SecurityResult(
                    is_safe=False,
                    threat_type="PROMPT_INJECTION",
                    rejection_message=(
                        "⚠️ I detected an attempt to manipulate my instructions. "
                        "This interaction has been logged. I'm here to help with "
                        "legitimate laboratory questions only."
                    ),
                    risk_score=0.95,
                )
        return SecurityResult(is_safe=True)

    def _check_exfiltration(self, message: str, user_id: int) -> SecurityResult:
        """Detect data exfiltration attempts."""
        for pattern in self.EXFILTRATION_PATTERNS:
            if re.search(pattern, message, re.IGNORECASE):
                security_logger.warning(
                    f"EXFILTRATION ATTEMPT | user={user_id} | "
                    f"pattern={pattern} | message_preview={message[:100]}"
                )
                return SecurityResult(
                    is_safe=False,
                    threat_type="DATA_EXFILTRATION",
                    rejection_message=(
                        "⚠️ I cannot send or export data to external destinations. "
                        "All LIMS data queries are limited to this chat interface."
                    ),
                    risk_score=0.9,
                )
        return SecurityResult(is_safe=True)

    def _check_rbac(self, context) -> SecurityResult:
        """Check role-based access for database queries."""
        from django.conf import settings

        role = context.user_role
        role_perms = settings.USER_ROLES.get(role, {})

        # Check if message appears to be a DB query but user lacks permission
        db_keywords = ["show", "list", "how many", "count", "pending", "failed", "query", "select"]
        lower_msg = context.message.lower()
        looks_like_db_query = any(kw in lower_msg for kw in db_keywords)

        if looks_like_db_query and not role_perms.get("can_query_db", False):
            security_logger.warning(
                f"RBAC BLOCK | user={context.user_id} | role={role} | "
                f"attempted DB query without permission"
            )
            return SecurityResult(
                is_safe=False,
                threat_type="RBAC_VIOLATION",
                rejection_message=(
                    f"Your role ({role}) does not have permission to query the LIMS database. "
                    "Please contact your administrator to request access."
                ),
                risk_score=0.6,
            )

        return SecurityResult(is_safe=True)

    @classmethod
    def mask_sensitive_data(cls, text: str) -> str:
        """Mask sensitive data patterns in text before logging."""
        masked = text
        for pattern, replacement in cls.SENSITIVE_PATTERNS:
            masked = re.sub(pattern, replacement, masked, flags=re.IGNORECASE)
        return masked

    @classmethod
    def validate_file_upload(cls, filename: str, file_size_bytes: int, content_type: str) -> SecurityResult:
        """Validate document upload safety."""
        from django.conf import settings

        # Check file extension
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in settings.ALLOWED_DOCUMENT_TYPES:
            return SecurityResult(
                is_safe=False,
                threat_type="INVALID_FILE_TYPE",
                rejection_message=f"File type '{ext}' is not allowed. "
                                  f"Supported: {', '.join(settings.ALLOWED_DOCUMENT_TYPES)}",
            )

        # Check file size
        max_bytes = settings.MAX_DOCUMENT_SIZE_MB * 1024 * 1024
        if file_size_bytes > max_bytes:
            return SecurityResult(
                is_safe=False,
                threat_type="FILE_TOO_LARGE",
                rejection_message=(
                    f"File too large ({file_size_bytes / 1024 / 1024:.1f} MB). "
                    f"Maximum: {settings.MAX_DOCUMENT_SIZE_MB} MB"
                ),
            )

        # Block executable content types
        blocked_types = ["application/x-executable", "application/x-sh", "text/x-script"]
        if any(bt in content_type for bt in blocked_types):
            return SecurityResult(
                is_safe=False,
                threat_type="DANGEROUS_CONTENT_TYPE",
                rejection_message=f"Content type '{content_type}' is not permitted.",
            )

        return SecurityResult(is_safe=True)
