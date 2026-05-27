"""
Workflow Manager - FIXED
Key fix: all Django ORM calls wrapped with sync_to_async
so they work correctly inside async Django views.
"""

import logging
from typing import Optional, Tuple
from asgiref.sync import sync_to_async

from apps.agents.workflow_definitions import (
    get_workflow_by_trigger,
    get_workflow_by_id,
)

logger = logging.getLogger("lab_assistant")


# ── Validation ────────────────────────────────────────────────────────────────

def validate_input(value: str, rule: str, field: str = "") -> Tuple[bool, str, str]:
    from datetime import datetime
    from apps.agents.workflow_definitions import CHOICE_MAPS

    value = value.strip()
    if not value:
        return False, "", "Please enter a value."

    if rule.startswith("number"):
        parts = rule.split(":")
        min_val = int(parts[1]) if len(parts) > 1 else 1
        max_val = int(parts[2]) if len(parts) > 2 else 9999
        try:
            n = int(value)
            if min_val <= n <= max_val:
                return True, str(n), ""
            return False, "", f"Please enter a number between {min_val} and {max_val}."
        except ValueError:
            return False, "", f"'{value}' is not a valid number."

    if rule == "date":
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value, fmt)
                return True, dt.strftime("%d-%m-%Y"), ""
            except ValueError:
                continue
        return False, "", f"Invalid date. Use DD-MM-YYYY format e.g. 25-05-2026"

    if rule == "yesno":
        if value.upper() in ("YES", "Y", "CONFIRM", "OK", "PROCEED"):
            return True, "YES", ""
        if value.upper() in ("NO", "N", "CANCEL", "STOP", "ABORT"):
            return True, "NO", ""
        return False, "", "Please type YES to confirm or NO to cancel."

    if rule.startswith("choice:"):
        allowed = [c.strip() for c in rule.split(":", 1)[1].split(",")]
        choice_map = CHOICE_MAPS.get(field, {})
        # Check direct match
        for a in allowed:
            if value.upper() == a.upper():
                clean = choice_map.get(value, choice_map.get(a, a))
                return True, clean, ""
        # Check number alias
        if value in choice_map:
            return True, choice_map[value], ""
        options = ", ".join([f"{k}={v}" for k, v in choice_map.items()] or allowed)
        return False, "", f"Invalid choice. Options: {options}"

    if rule == "text":
        return (True, value, "") if value else (False, "", "Please enter a value.")

    return True, value, ""


def format_ask(template: str, collected_data: dict) -> str:
    try:
        return template.format(**collected_data)
    except KeyError:
        return template


# ── DB helpers wrapped for async use ─────────────────────────────────────────

@sync_to_async
def _get_active_workflow(session_id: str):
    from apps.chat.models import WorkflowSession
    return WorkflowSession.objects.filter(
        chat_session_id=session_id,
        status="active"
    ).first()


@sync_to_async
def _create_workflow(session_id: str, workflow_id: str, workflow_name: str, first_step: dict):
    from apps.chat.models import WorkflowSession
    return WorkflowSession.objects.create(
        chat_session_id    = session_id,
        workflow_id        = workflow_id,
        workflow_name      = workflow_name,
        current_step       = first_step["id"],
        current_step_index = 0,
        collected_data     = {},
        status             = "active",
    )


@sync_to_async
def _save_workflow(wf_session, fields=None):
    if fields:
        wf_session.save(update_fields=fields)
    else:
        wf_session.save()
    return wf_session


@sync_to_async
def _mark_completed(wf_session, result: dict):
    from django.utils import timezone
    wf_session.status       = "completed"
    wf_session.completed_at = timezone.now()
    wf_session.result       = result
    wf_session.save(update_fields=["status", "completed_at", "result"])


@sync_to_async
def _mark_cancelled(wf_session):
    from django.utils import timezone
    wf_session.status       = "cancelled"
    wf_session.completed_at = timezone.now()
    wf_session.save(update_fields=["status", "completed_at"])


# ── WorkflowManager ───────────────────────────────────────────────────────────

class WorkflowManager:

    def detect_trigger(self, message: str) -> Optional[dict]:
        """Synchronous — safe to call from sync context."""
        if message.strip().upper() in ("CANCEL", "STOP", "ABORT", "QUIT"):
            return None
        return get_workflow_by_trigger(message)

    def get_active_workflow_sync(self, session_id: str):
        """Synchronous version — use only from sync views."""
        from apps.chat.models import WorkflowSession
        return WorkflowSession.objects.filter(
            chat_session_id=session_id,
            status="active"
        ).first()

    def start_workflow_sync(self, session_id: str, workflow_id: str):
        """Synchronous version — use only from sync views."""
        from apps.chat.models import WorkflowSession

        wf_def     = get_workflow_by_id(workflow_id)
        first_step = wf_def["steps"][0]
        steps      = wf_def["steps"]

        wf_session = WorkflowSession.objects.create(
            chat_session_id    = session_id,
            workflow_id        = workflow_id,
            workflow_name      = wf_def["name"],
            current_step       = first_step["id"],
            current_step_index = 0,
            collected_data     = {},
            status             = "active",
        )

        intro = (
            f"** {wf_def['name']}**\n\n"
            f"I'll guide you through this step by step.\n"
            f"Type CANCEL at any time to stop.\n\n"
            f"**Step 1 of {len(steps) - 1}:**\n"
            f"{first_step['ask']}"
        )
        return wf_session, intro

    def process_sync(self, session_id: str, message: str, user_role: str) -> Tuple[str, bool, Optional[dict]]:
        """
        Synchronous version of process — called from sync Django views.
        All DB operations done synchronously here.
        """
        from apps.chat.models import WorkflowSession

        # Cancel check
        if message.strip().upper() in ("CANCEL", "STOP", "ABORT", "QUIT"):
            WorkflowSession.objects.filter(
                chat_session_id=session_id, status="active"
            ).update(status="cancelled")
            return "Workflow cancelled. No changes were made. How else can I help?", False, None

        # Get active workflow
        wf_session = WorkflowSession.objects.filter(
            chat_session_id=session_id,
            status="active"
        ).first()

        if not wf_session:
            return "No active workflow found.", False, None

        wf_def = get_workflow_by_id(wf_session.workflow_id)
        steps  = wf_def["steps"]
        idx    = wf_session.current_step_index
        step   = steps[idx]

        # Help request
        if message.strip().lower() in ("help", "?", "hint"):
            help_text = step.get("help_text", "Please answer the question above.")
            return f"Hint: {help_text}", True, None

        # Validate input
        rule     = step.get("validate", "text")
        field    = step.get("field", step["id"])
        is_valid, clean_value, error_msg = validate_input(message, rule, field)

        if not is_valid:
            return (
                f"{error_msg}\n\n"
                f"**Step {idx + 1}:** {step['ask']}\n\n"
                f"(Type help for guidance or CANCEL to stop)",
                True, None,
            )

        # Store answer
        collected = dict(wf_session.collected_data)
        collected[field] = clean_value
        wf_session.collected_data = collected

        # Confirmation step
        if step.get("validate") == "yesno":
            if clean_value == "NO":
                wf_session.status = "cancelled"
                from django.utils import timezone
                wf_session.completed_at = timezone.now()
                wf_session.save()
                return "Cancelled. No changes were made. How else can I help?", False, None

            # YES — execute
            wf_session.save()
            return self._execute_sync(wf_session, wf_def, user_role)

        # Move to next step
        next_idx  = idx + 1
        next_step = steps[next_idx]
        wf_session.current_step       = next_step["id"]
        wf_session.current_step_index = next_idx
        wf_session.save()

        is_confirm = next_step.get("validate") == "yesno"
        label      = "Confirmation" if is_confirm else f"Step {next_idx + 1} of {len(steps) - 1}"
        next_ask   = format_ask(next_step["ask"], wf_session.collected_data)

        return f"Got it!\n\n**{label}:**\n{next_ask}", True, None

    def _execute_sync(self, wf_session, wf_def: dict, user_role: str) -> Tuple[str, bool, Optional[dict]]:
        """Execute workflow synchronously after confirmation."""
        import asyncio
        from apps.agents.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor()
        fn_name  = wf_def.get("execute_fn", "execute_generic")

        try:
            # Run async executor in sync context
            loop   = asyncio.new_event_loop()
            result = loop.run_until_complete(
                executor.execute(fn_name, wf_session.collected_data, user_role)
            )
            loop.close()

            from django.utils import timezone
            wf_session.status       = "completed"
            wf_session.completed_at = timezone.now()
            wf_session.result       = result
            wf_session.save()

            return result["message"], False, result

        except Exception as e:
            logger.error(f"Workflow execution error: {e}", exc_info=True)
            wf_session.status = "cancelled"
            wf_session.save()
            return f"Error executing workflow: {str(e)}", False, None