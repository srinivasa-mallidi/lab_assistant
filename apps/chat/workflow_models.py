"""
workflow_models.py
WorkflowSession is now defined in models.py directly.
This file re-exports it for backward compatibility.
"""
from apps.chat.models import WorkflowSession

__all__ = ["WorkflowSession"]