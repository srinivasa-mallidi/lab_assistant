"""
Workflow Definitions
All guided multi-turn workflows defined here as configuration.
To add a new workflow — just add a new entry to WORKFLOWS dict.
No code changes needed anywhere else.
"""

# ─── Workflow Registry ────────────────────────────────────────────────────────
#
# Each workflow has:
#   name          : display name
#   description   : what it does
#   triggers      : phrases that activate this workflow
#   requires_role : minimum role needed
#   steps         : ordered list of questions to ask
#   execute_fn    : function name in workflow_executor.py to call at the end
#
# Each step has:
#   id            : unique step identifier
#   ask           : question to show user (supports {variable} placeholders)
#   field         : key to store the answer in collected_data
#   validate      : "number" | "date" | "yesno" | "text" | "choice:A,B,C"
#   optional      : True if user can skip (default False)
#   help_text     : shown if user types "help" at this step
# ─────────────────────────────────────────────────────────────────────────────

WORKFLOWS = {

    # ── 1. Create Vessel Unloading Samples ────────────────────────────────────
    "create_vessel_samples": {
        "name": "Create Vessel Unloading Samples",
        "description": "Creates samples for each compartment of an unloading vessel",
        "triggers": [
            "create samples for vessel",
            "vessel unloading",
            "create vessel samples",
            "new vessel samples",
            "log vessel",
            "unloading samples",
        ],
        "requires_role": "LAB_ANALYST",
        "steps": [
            {
                "id":        "compartment_count",
                "ask":       "How many compartments does the vessel have?",
                "field":     "compartment_count",
                "validate":  "number:1:50",
                "help_text": "Enter a number between 1 and 50.",
            },
            {
                "id":        "vessel_name",
                "ask":       "What is the vessel name?",
                "field":     "vessel_name",
                "validate":  "text",
                "help_text": "Enter the full vessel name e.g. MV Atlantic Star",
            },
            {
                "id":        "arrival_date",
                "ask":       "What is the vessel arrival date? (DD-MM-YYYY)",
                "field":     "arrival_date",
                "validate":  "date",
                "help_text": "Enter date in format DD-MM-YYYY e.g. 25-05-2026",
            },
            {
                "id":        "product_type",
                "ask":       "What product is being unloaded?\n"
                             "1. Crude Oil\n"
                             "2. Fuel Oil\n"
                             "3. Lubricants\n"
                             "4. Other\n"
                             "Enter number or name:",
                "field":     "product_type",
                "validate":  "choice:Crude Oil,Fuel Oil,Lubricants,Other,1,2,3,4",
                "help_text": "Type the number or the product name.",
            },
            {
                "id":        "priority",
                "ask":       "What is the priority?\n"
                             "1. ROUTINE\n"
                             "2. URGENT\n"
                             "3. STAT\n"
                             "Enter number or name:",
                "field":     "priority",
                "validate":  "choice:ROUTINE,URGENT,STAT,1,2,3",
                "help_text": "STAT = immediate, URGENT = same day, ROUTINE = normal.",
            },
            {
                "id":        "confirm",
                "ask":       "📋 **Please confirm the following:**\n\n"
                             "  Vessel      : {vessel_name}\n"
                             "  Arrival     : {arrival_date}\n"
                             "  Product     : {product_type}\n"
                             "  Compartments: {compartment_count}\n"
                             "  Priority    : {priority}\n\n"
                             "This will create **{compartment_count} samples** "
                             "in SampleManager.\n\n"
                             "Type **YES** to proceed or **NO** to cancel:",
                "field":     "confirmed",
                "validate":  "yesno",
                "help_text": "Type YES to create the samples or NO to cancel.",
            },
        ],
        "execute_fn": "execute_create_vessel_samples",
    },

    # ── 2. Log Test Result ─────────────────────────────────────────────────────
    "log_test_result": {
        "name": "Log Test Result",
        "description": "Manually log a test result for a sample",
        "triggers": [
            "log test result",
            "enter test result",
            "add test result",
            "record result",
            "log result",
        ],
        "requires_role": "LAB_ANALYST",
        "steps": [
            {
                "id":       "sample_id",
                "ask":      "Enter the Sample ID:",
                "field":    "sample_id",
                "validate": "text",
                "help_text":"Sample ID format e.g. S-2026-001",
            },
            {
                "id":       "test_code",
                "ask":      "Enter the Test Code:",
                "field":    "test_code",
                "validate": "text",
                "help_text":"Test code from the test catalogue e.g. VISC-40",
            },
            {
                "id":       "result_value",
                "ask":      "Enter the result value:",
                "field":    "result_value",
                "validate": "text",
                "help_text":"Enter the numeric or text result value.",
            },
            {
                "id":       "result_status",
                "ask":      "What is the result status?\n"
                            "1. PASS\n2. FAIL\n3. RETEST_REQUIRED\n"
                            "Enter number or name:",
                "field":    "result_status",
                "validate": "choice:PASS,FAIL,RETEST_REQUIRED,1,2,3",
                "help_text":"Select the status of this test result.",
            },
            {
                "id":       "confirm",
                "ask":      "📋 **Confirm Test Result:**\n\n"
                            "  Sample ID : {sample_id}\n"
                            "  Test Code : {test_code}\n"
                            "  Result    : {result_value}\n"
                            "  Status    : {result_status}\n\n"
                            "Type **YES** to log or **NO** to cancel:",
                "field":    "confirmed",
                "validate": "yesno",
            },
        ],
        "execute_fn": "execute_log_test_result",
    },

    # ── 3. Request Sample Approval ─────────────────────────────────────────────
    "request_approval": {
        "name": "Request Sample Approval",
        "description": "Submit a sample for supervisor approval",
        "triggers": [
            "request approval",
            "submit for approval",
            "send for approval",
            "approve sample",
            "request sample approval",
        ],
        "requires_role": "LAB_ANALYST",
        "steps": [
            {
                "id":       "sample_id",
                "ask":      "Enter the Sample ID to submit for approval:",
                "field":    "sample_id",
                "validate": "text",
            },
            {
                "id":       "approval_stage",
                "ask":      "Which approval stage?\n"
                            "1. ANALYST_REVIEW\n"
                            "2. SUPERVISOR_APPROVAL\n"
                            "3. QA_SIGNOFF\n"
                            "Enter number:",
                "field":    "approval_stage",
                "validate": "choice:ANALYST_REVIEW,SUPERVISOR_APPROVAL,QA_SIGNOFF,1,2,3",
            },
            {
                "id":       "comments",
                "ask":      "Add any comments (or type NONE to skip):",
                "field":    "comments",
                "validate": "text",
                "optional": True,
            },
            {
                "id":       "confirm",
                "ask":      "📋 **Confirm Approval Request:**\n\n"
                            "  Sample ID : {sample_id}\n"
                            "  Stage     : {approval_stage}\n"
                            "  Comments  : {comments}\n\n"
                            "Type **YES** to submit or **NO** to cancel:",
                "field":    "confirmed",
                "validate": "yesno",
            },
        ],
        "execute_fn": "execute_request_approval",
    },

    # ── 4. Retest Failed Sample ────────────────────────────────────────────────
    "retest_sample": {
        "name": "Schedule Sample Retest",
        "description": "Schedule a retest for a failed sample",
        "triggers": [
            "retest sample",
            "schedule retest",
            "retest failed",
            "failed sample retest",
            "request retest",
        ],
        "requires_role": "LAB_ANALYST",
        "steps": [
            {
                "id":       "sample_id",
                "ask":      "Enter the Sample ID to retest:",
                "field":    "sample_id",
                "validate": "text",
            },
            {
                "id":       "reason",
                "ask":      "What is the reason for retest?\n"
                            "1. Equipment Failure\n"
                            "2. Sample Contamination\n"
                            "3. Analyst Error\n"
                            "4. Out of Specification\n"
                            "5. Other\n"
                            "Enter number or reason:",
                "field":    "reason",
                "validate": "text",
            },
            {
                "id":       "priority",
                "ask":      "Priority for retest?\n1. ROUTINE\n2. URGENT\n3. STAT",
                "field":    "priority",
                "validate": "choice:ROUTINE,URGENT,STAT,1,2,3",
            },
            {
                "id":       "confirm",
                "ask":      "📋 **Confirm Retest Request:**\n\n"
                            "  Sample ID : {sample_id}\n"
                            "  Reason    : {reason}\n"
                            "  Priority  : {priority}\n\n"
                            "Type **YES** to schedule or **NO** to cancel:",
                "field":    "confirmed",
                "validate": "yesno",
            },
        ],
        "execute_fn": "execute_retest_sample",
    },
}


# ── Choice mappings (number aliases) ──────────────────────────────────────────
CHOICE_MAPS = {
    "product_type": {"1": "Crude Oil", "2": "Fuel Oil", "3": "Lubricants", "4": "Other"},
    "priority":     {"1": "ROUTINE",   "2": "URGENT",   "3": "STAT"},
    "result_status":{"1": "PASS",      "2": "FAIL",     "3": "RETEST_REQUIRED"},
    "approval_stage":{"1":"ANALYST_REVIEW","2":"SUPERVISOR_APPROVAL","3":"QA_SIGNOFF"},
}


def get_workflow_by_trigger(message: str) -> dict | None:
    """Find workflow matching a user message trigger phrase."""
    msg_lower = message.lower().strip()
    for wf_id, wf in WORKFLOWS.items():
        for trigger in wf["triggers"]:
            if trigger in msg_lower:
                return {"id": wf_id, **wf}
    return None


def get_workflow_by_id(wf_id: str) -> dict | None:
    """Get a workflow definition by its ID."""
    wf = WORKFLOWS.get(wf_id)
    if wf:
        return {"id": wf_id, **wf}
    return None