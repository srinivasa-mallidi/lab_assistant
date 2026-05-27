"""
Security Middleware
Audit logging and prompt injection detection at the request level.
"""

import json
import time
import logging

audit_logger = logging.getLogger("audit")
security_logger = logging.getLogger("security")


class AuditLogMiddleware:
    """Logs all API requests for compliance audit trail."""

    AUDIT_PATHS = ["/api/v1/chat", "/api/v1/documents", "/api/v1/history"]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.time()
        response = self.get_response(request)
        elapsed_ms = int((time.time() - start) * 1000)

        if any(request.path.startswith(p) for p in self.AUDIT_PATHS):
            user = request.user.username if request.user.is_authenticated else "anonymous"
            audit_logger.info(
                f"API | user={user} | method={request.method} | "
                f"path={request.path} | status={response.status_code} | "
                f"ip={self._get_ip(request)} | ms={elapsed_ms}"
            )

        return response

    @staticmethod
    def _get_ip(request) -> str:
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded:
            return x_forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")


class PromptInjectionMiddleware:
    """Quick pattern-based injection check at middleware level (before agent)."""

    QUICK_PATTERNS = [
        "ignore previous",
        "forget instructions",
        "system prompt",
        "jailbreak",
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and "/api/v1/chat" in request.path:
            try:
                body = json.loads(request.body.decode("utf-8"))
                message = body.get("message", "").lower()
                for pattern in self.QUICK_PATTERNS:
                    if pattern in message:
                        user = request.user.username if request.user.is_authenticated else "anonymous"
                        security_logger.warning(
                            f"QUICK INJECTION CHECK | user={user} | pattern='{pattern}' | "
                            f"ip={request.META.get('REMOTE_ADDR', '?')}"
                        )
                        break
            except Exception:
                pass

        return self.get_response(request)
