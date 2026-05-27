"""
Workflow Executor
Executes the final action after user confirms a workflow.
Currently generates a summary + simulated LIMS response.
When write access to Oracle is granted, replace the simulation
blocks with real INSERT/UPDATE calls.
"""

import logging
from datetime import datetime, date
from typing import Optional

logger      = logging.getLogger("lab_assistant")
audit_logger = logging.getLogger("audit")


class WorkflowExecutor:
    """
    Executes workflow actions after user confirmation.

    Each execute_* method receives collected_data dict and returns:
    {
        "success": True/False,
        "message": "human-readable result to show in chat",
        "data":    {...}  # any data to store
    }
    """

    async def execute(self, fn_name: str, data: dict, user_role: str) -> dict:
        """Dispatch to the correct execute method."""
        handler = getattr(self, fn_name, self.execute_generic)
        return await handler(data, user_role)

    # ── 1. Create Vessel Samples ──────────────────────────────────────────────
    async def execute_create_vessel_samples(self, data: dict, user_role: str) -> dict:
        count        = int(data.get("compartment_count", 1))
        vessel       = data.get("vessel_name", "Unknown")
        arrival      = data.get("arrival_date", "")
        product      = data.get("product_type", "")
        priority     = data.get("priority", "ROUTINE")

        # ── Generate sample IDs ───────────────────────────────────────────
        year = datetime.now().year
        # In production: query Oracle for next sequence number
        # e.g. SELECT LIMS_SEQ.NEXTVAL FROM DUAL
        # For now: generate placeholder IDs
        today_str = datetime.now().strftime("%Y%m%d")
        sample_ids = [
            f"S-{year}-VES-{today_str}-{str(i+1).zfill(3)}"
            for i in range(count)
        ]

        # ── Audit log ─────────────────────────────────────────────────────
        audit_logger.info(
            f"WORKFLOW_EXECUTE | create_vessel_samples | "
            f"vessel={vessel} | count={count} | priority={priority} | "
            f"samples={sample_ids}"
        )

        # ── In production — INSERT into Oracle ────────────────────────────
        # from apps.agents.database_agent import LIMSConnection
        # conn = LIMSConnection.get_connection(settings.LIMS_DATABASE)
        # cursor = conn.cursor()
        # for i, sid in enumerate(sample_ids):
        #     cursor.execute("""
        #         INSERT INTO SAMPLES
        #         (SAMPLE_ID, SAMPLE_NAME, STATUS, SAMPLE_TYPE,
        #          RECEIVED_DATE, ANALYST_ID, PRIORITY)
        #         VALUES (:1, :2, 'PENDING', :3, SYSDATE, :4, :5)
        #     """, [sid, f"{vessel} Compartment {i+1}", product, user_role, priority])
        # conn.commit()
        # ─────────────────────────────────────────────────────────────────

        # Build success message
        ids_display = "\n".join([f"  • {sid}" for sid in sample_ids])
        message = (
            f"✅ **{count} samples created successfully!**\n\n"
            f"**Vessel:** {vessel}\n"
            f"**Arrival:** {arrival}\n"
            f"**Product:** {product}\n"
            f"**Priority:** {priority}\n\n"
            f"**Sample IDs created:**\n{ids_display}\n\n"
            f"All samples are now in **PENDING** status in SampleManager.\n"
            f"Assigned analyst: {user_role}"
        )

        return {
            "success":    True,
            "message":    message,
            "sample_ids": sample_ids,
            "count":      count,
        }

    # ── 2. Log Test Result ─────────────────────────────────────────────────────
    async def execute_log_test_result(self, data: dict, user_role: str) -> dict:
        sample_id     = data.get("sample_id", "")
        test_code     = data.get("test_code", "")
        result_value  = data.get("result_value", "")
        result_status = data.get("result_status", "PASS")

        result_id = f"R-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        audit_logger.info(
            f"WORKFLOW_EXECUTE | log_test_result | "
            f"sample={sample_id} | test={test_code} | "
            f"result={result_value} | status={result_status}"
        )

        # ── In production — INSERT into TEST_RESULTS ──────────────────────
        # cursor.execute("""
        #     INSERT INTO TEST_RESULTS
        #     (RESULT_ID, SAMPLE_ID, TEST_CODE, RESULT_VALUE,
        #      RESULT_STATUS, ANALYST_ID, TESTED_DATE)
        #     VALUES (:1, :2, :3, :4, :5, :6, SYSDATE)
        # """, [result_id, sample_id, test_code, result_value, result_status, user_role])
        # ─────────────────────────────────────────────────────────────────

        status_icon = "✅" if result_status == "PASS" else "❌" if result_status == "FAIL" else "🔄"

        message = (
            f"{status_icon} **Test result logged successfully!**\n\n"
            f"**Result ID :** {result_id}\n"
            f"**Sample ID :** {sample_id}\n"
            f"**Test Code :** {test_code}\n"
            f"**Result    :** {result_value}\n"
            f"**Status    :** {result_status}\n\n"
            f"Logged by: {user_role} at {datetime.now().strftime('%d-%m-%Y %H:%M')}"
        )

        return {
            "success":   True,
            "message":   message,
            "result_id": result_id,
        }

    # ── 3. Request Approval ────────────────────────────────────────────────────
    async def execute_request_approval(self, data: dict, user_role: str) -> dict:
        sample_id      = data.get("sample_id", "")
        approval_stage = data.get("approval_stage", "")
        comments       = data.get("comments", "None")

        approval_id = f"APR-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        audit_logger.info(
            f"WORKFLOW_EXECUTE | request_approval | "
            f"sample={sample_id} | stage={approval_stage}"
        )

        message = (
            f"✅ **Approval request submitted!**\n\n"
            f"**Approval ID :** {approval_id}\n"
            f"**Sample ID   :** {sample_id}\n"
            f"**Stage       :** {approval_stage}\n"
            f"**Comments    :** {comments}\n"
            f"**Requested by:** {user_role}\n"
            f"**Status      :** PENDING\n\n"
            f"The supervisor will be notified to review this sample."
        )

        return {
            "success":     True,
            "message":     message,
            "approval_id": approval_id,
        }

    # ── 4. Retest Sample ───────────────────────────────────────────────────────
    async def execute_retest_sample(self, data: dict, user_role: str) -> dict:
        sample_id = data.get("sample_id", "")
        reason    = data.get("reason", "")
        priority  = data.get("priority", "ROUTINE")

        retest_id = f"RT-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        audit_logger.info(
            f"WORKFLOW_EXECUTE | retest_sample | "
            f"sample={sample_id} | reason={reason} | priority={priority}"
        )

        message = (
            f"🔄 **Retest scheduled successfully!**\n\n"
            f"**Retest ID  :** {retest_id}\n"
            f"**Sample ID  :** {sample_id}\n"
            f"**Reason     :** {reason}\n"
            f"**Priority   :** {priority}\n"
            f"**Requested  :** {user_role}\n\n"
            f"The sample has been queued for retesting with **{priority}** priority."
        )

        return {
            "success":   True,
            "message":   message,
            "retest_id": retest_id,
        }

    # ── Generic fallback ───────────────────────────────────────────────────────
    async def execute_generic(self, data: dict, user_role: str) -> dict:
        audit_logger.info(f"WORKFLOW_EXECUTE | generic | data={data}")
        message = (
            f"✅ **Workflow completed!**\n\n"
            f"**Data collected:**\n"
            + "\n".join([f"  • {k}: {v}" for k, v in data.items() if k != "confirmed"])
            + f"\n\nLogged by: {user_role} at {datetime.now().strftime('%d-%m-%Y %H:%M')}"
        )
        return {"success": True, "message": message, "data": data}