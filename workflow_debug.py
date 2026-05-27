"""
workflow_debug.py - v2 (sync version, encoding fixed)
Run: python workflow_debug.py
"""
import os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import django
django.setup()

print("=" * 60)
print("  LabAssist Workflow Diagnostic v2")
print("=" * 60)

# 1. Clear stuck workflows
print("\n[1] Clearing stuck workflows...")
from apps.chat.models import WorkflowSession, ChatSession, Message
count = WorkflowSession.objects.filter(status="active").update(status="cancelled")
print(f"    Cleared: {count}")

# 2. Test trigger detection
print("\n[2] Testing trigger detection...")
from apps.agents.workflow_manager import WorkflowManager
wm = WorkflowManager()
result = wm.detect_trigger("create samples for vessel unloading")
print(f"    Trigger: {result['id'] if result else 'NOT FOUND'}")

# 3. Full sync flow test
print("\n[3] Testing full sync workflow flow...")
try:
    from django.contrib.auth.models import User
    user = User.objects.filter(is_superuser=True).first() or User.objects.first()
    print(f"    User: {user.username}")

    # Fresh session
    session = ChatSession.objects.create(user=user, title="DEBUG", model_used="llama3")
    print(f"    Session: {session.id}")

    # Start workflow
    wf_session, q1 = wm.start_workflow_sync(str(session.id), "create_vessel_samples")
    print(f"    Q1: {q1[:60]}...")

    # Answer step 1
    r2, active, _ = wm.process_sync(str(session.id), "6", "LAB_ANALYST")
    print(f"    A1=6 -> active={active}")
    print(f"    Q2: {r2[:60]}...")

    # Answer step 2
    r3, active, _ = wm.process_sync(str(session.id), "MV Atlantic", "LAB_ANALYST")
    print(f"    A2=MV Atlantic -> active={active}")
    print(f"    Q3: {r3[:60]}...")

    # Cleanup
    session.delete()
    print("\n    FULL SYNC FLOW: OK")

except Exception as e:
    print(f"    ERROR: {e}")
    import traceback; traceback.print_exc()

# 4. Check views.py
print("\n[4] Checking views.py...")
views_path = os.path.join("apps", "api", "views.py")
with open(views_path, encoding="utf-8", errors="replace") as f:
    vc = f.read()
checks = {
    "process_sync":       "process_sync" in vc,
    "start_workflow_sync":"start_workflow_sync" in vc,
    "detect_trigger":     "detect_trigger" in vc,
    "workflow_active":    "workflow_active" in vc,
}
for k, v in checks.items():
    print(f"    {'OK' if v else 'MISSING'}: {k}")

print("\n" + "="*60)
all_ok = all(checks.values())
if all_ok:
    print("  ALL CHECKS PASSED")
    print("\n  Steps to run now:")
    print("  1. python manage.py runserver")
    print("  2. Browser: Ctrl+Shift+Delete -> clear cache")
    print("  3. Open localhost:8000")
    print("  4. Click New Conversation")
    print("  5. Type: create samples for vessel unloading")
else:
    print("  SOME CHECKS FAILED - re-copy the files above")
print("="*60)