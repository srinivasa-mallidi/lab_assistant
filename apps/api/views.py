"""
API Views
REST endpoints for the Lab Assistant chatbot.
"""

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

from django.contrib.auth.models import User
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

# ── Chat / Document models (safe to import at module level) ───────────────────
from apps.chat.models import ChatSession, Message, MessageFeedback, ConversationMemory
from apps.documents.models import Document as LabDocument

logger = logging.getLogger("lab_assistant")
audit_logger = logging.getLogger("audit")

# ── Lazy singletons — AI agents loaded on first request, not at import time ───
# This prevents Django startup from loading torch/chromadb/sentence-transformers
# before migrations have run, and gives much faster manage.py startup.
_orchestrator = None
_doc_agent = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from apps.agents.orchestrator import OrchestratorAgent
        _orchestrator = OrchestratorAgent()
    return _orchestrator


def get_doc_agent():
    global _doc_agent
    if _doc_agent is None:
        from apps.agents.document_agent import DocumentAgent
        _doc_agent = DocumentAgent()
    return _doc_agent


def get_user_role(user: User) -> str:
    """Get user's LIMS role from profile or groups."""
    try:
        profile = user.userprofile
        return profile.role
    except Exception:
        if user.is_superuser:
            return "LIMS_ADMIN"
        if user.groups.filter(name="LAB_SUPERVISOR").exists():
            return "LAB_SUPERVISOR"
        return "LAB_ANALYST"


class ChatRateThrottle(UserRateThrottle):
    scope = "chat"


class ChatView(APIView):
    """POST /api/v1/chat - Process a chat message."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [ChatRateThrottle]

    def post(self, request):
        message    = request.data.get("message", "").strip()
        session_id = request.data.get("session_id")
        model      = request.data.get("model", "llama3")
        stream     = request.data.get("stream", False)

        if not message:
            return Response({"error": "Message is required"}, status=400)

        # Get or create session
        if session_id:
            try:
                session = ChatSession.objects.get(
                    id=session_id, user=request.user, status=ChatSession.Status.ACTIVE
                )
            except ChatSession.DoesNotExist:
                return Response({"error": "Session not found"}, status=404)
        else:
            session = ChatSession.objects.create(
                user=request.user,
                title=message[:80],
                model_used=model,
            )

        # Save user message
        user_message = Message.objects.create(
            session=session,
            role=Message.Role.USER,
            content=message,
        )

        user_role = get_user_role(request.user)

        # ── Workflow interception ──────────────────────────────────────────
        from apps.agents.workflow_manager import WorkflowManager
        from apps.chat.models import WorkflowSession
        wm = WorkflowManager()

        # Cancel check
        if message.strip().upper() in ("CANCEL", "STOP", "ABORT"):
            WorkflowSession.objects.filter(
                chat_session=session, status="active"
            ).update(status="cancelled")
            response_text = "Workflow cancelled. How can I help you?"
            assistant_msg = Message.objects.create(
                session=session,
                role=Message.Role.ASSISTANT,
                content=response_text,
                intent_type="workflow",
            )
            return Response({
                "message_id":      str(assistant_msg.id),
                "session_id":      str(session.id),
                "response":        response_text,
                "intent":          "workflow",
                "workflow_active": False,
                "sources":         [],
                "response_time_ms": 0,
            })

        # Case 1: Active workflow in THIS session -> continue it (sync)
        active_wf = WorkflowSession.objects.filter(
            chat_session=session, status="active"
        ).first()

        if active_wf:
            response_text, still_active, result = wm.process_sync(
                str(session.id), message, user_role
            )
            assistant_msg = Message.objects.create(
                session=session,
                role=Message.Role.ASSISTANT,
                content=response_text,
                intent_type="workflow",
                metadata={
                    "workflow_id":   active_wf.workflow_id,
                    "workflow_name": active_wf.workflow_name,
                    "still_active":  still_active,
                },
            )
            session.save(update_fields=["updated_at"])
            return Response({
                "message_id":      str(assistant_msg.id),
                "session_id":      str(session.id),
                "response":        response_text,
                "intent":          "workflow",
                "workflow_active": still_active,
                "sources":         [],
                "response_time_ms": 0,
            })

        # Case 2: No active workflow — check if message triggers one (sync)
        triggered_wf = wm.detect_trigger(message)
        if triggered_wf:
            required_role = triggered_wf.get("requires_role", "LAB_ANALYST")
            if not self._has_role(user_role, required_role):
                response_text = (
                    f"You need {required_role} role to use this workflow. "
                    f"Your current role: {user_role}"
                )
            else:
                _, response_text = wm.start_workflow_sync(
                    str(session.id), triggered_wf["id"]
                )

            assistant_msg = Message.objects.create(
                session=session,
                role=Message.Role.ASSISTANT,
                content=response_text,
                intent_type="workflow",
                metadata={"workflow_id": triggered_wf["id"]},
            )
            session.save(update_fields=["updated_at"])
            return Response({
                "message_id":      str(assistant_msg.id),
                "session_id":      str(session.id),
                "response":        response_text,
                "intent":          "workflow",
                "workflow_active": True,
                "sources":         [],
                "response_time_ms": 0,
            })
        # ── End workflow interception ──────────────────────────────────────

        # Normal flow — build history and route to Orchestrator
        recent_msgs = session.get_recent_messages(limit=8)
        history = [
            {"role": m.role, "content": m.content}
            for m in recent_msgs
        ]

        # Build agent context
        from apps.agents.orchestrator import AgentContext
        context = AgentContext(
            user_id=request.user.id,
            session_id=str(session.id),
            user_role=user_role,
            message=message,
            conversation_history=history,
        )

        if stream:
            return self._stream_response(context, session, request.user)
        else:
            return self._sync_response(context, session, user_message)

    @staticmethod
    def _has_role(user_role: str, required_role: str) -> bool:
        """Check if user_role meets the required_role level."""
        hierarchy = ["READ_ONLY", "LAB_ANALYST", "LAB_SUPERVISOR", "LIMS_ADMIN"]
        try:
            return hierarchy.index(user_role) >= hierarchy.index(required_role)
        except ValueError:
            return False

    def _sync_response(self, context, session: ChatSession, user_message: Message):
        """Non-streaming response."""
        start = time.time()
        orch = get_orchestrator()
        result = asyncio.run(orch.process(context))

        elapsed = int((time.time() - start) * 1000)

        # Save assistant message
        assistant_msg = Message.objects.create(
            session=session,
            role=Message.Role.ASSISTANT,
            content=result.final_response,
            intent_type=result.intent.value if result.intent else "general",
            sources=result.sources,
            sql_query=result.generated_sql,
            tokens_used=result.tokens_used,
            response_time_ms=elapsed,
        )

        # Update session
        session.updated_at = timezone.now()
        session.save(update_fields=["updated_at"])

        return Response({
            "message_id": str(assistant_msg.id),
            "session_id": str(session.id),
            "response": result.final_response,
            "intent": result.intent.value if result.intent else "general",
            "sources": result.sources,
            "response_time_ms": elapsed,
            "error": result.error,
        })

    def _stream_response(self, context, session: ChatSession, user: User):
        """Streaming SSE response."""
        orch = get_orchestrator()

        def generate():
            full_response = ""
            try:
                # Run async generator in sync context
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def stream_chunks():
                    nonlocal full_response
                    async for chunk in orch.stream(context):
                        full_response += chunk
                        data = json.dumps({"chunk": chunk, "done": False})
                        yield f"data: {data}\n\n"

                    # Final message
                    msg = Message.objects.create(
                        session=session,
                        role=Message.Role.ASSISTANT,
                        content=full_response,
                        intent_type=context.intent.value if context.intent else "general",
                        sources=context.sources,
                        sql_query=context.generated_sql,
                    )
                    session.save(update_fields=["updated_at"])

                    final_data = json.dumps({
                        "chunk": "",
                        "done": True,
                        "message_id": str(msg.id),
                        "session_id": str(session.id),
                        "sources": context.sources,
                        "intent": context.intent.value if context.intent else "general",
                    })
                    yield f"data: {final_data}\n\n"

                # Run the async generator
                for chunk_data in loop.run_until_complete(
                    _collect_async_gen(stream_chunks())
                ):
                    yield chunk_data

            except Exception as e:
                logger.error(f"Stream error: {e}", exc_info=True)
                yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

        return StreamingHttpResponse(generate(), content_type="text/event-stream")


async def _collect_async_gen(agen):
    results = []
    async for item in agen:
        results.append(item)
    return results


class SessionListView(APIView):
    """GET /api/v1/sessions - List user's chat sessions."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sessions = ChatSession.objects.filter(
            user=request.user,
            status=ChatSession.Status.ACTIVE
        ).values("id", "title", "model_used", "created_at", "updated_at")[:50]

        return Response({"sessions": list(sessions)})

    def post(self, request):
        """POST /api/v1/sessions - Create new session."""
        session = ChatSession.objects.create(
            user=request.user,
            title=request.data.get("title", "New Conversation"),
            model_used=request.data.get("model", "llama3"),
        )
        return Response({
            "session_id": str(session.id),
            "title": session.title,
            "created_at": session.created_at.isoformat(),
        }, status=201)


class HistoryView(APIView):
    """GET /api/v1/history/{session_id} - Get chat history."""
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            session = ChatSession.objects.get(id=session_id, user=request.user)
        except ChatSession.DoesNotExist:
            return Response({"error": "Session not found"}, status=404)

        messages = Message.objects.filter(
            session=session,
            role__in=[Message.Role.USER, Message.Role.ASSISTANT]
        ).values(
            "id", "role", "content", "intent_type",
            "sources", "created_at", "response_time_ms"
        )

        return Response({
            "session_id": str(session.id),
            "title": session.title,
            "messages": list(messages),
        })


class DocumentUploadView(APIView):
    """POST /api/v1/documents/upload - Upload and ingest a document."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_role = get_user_role(request.user)
        from django.conf import settings

        # RBAC check
        if not settings.USER_ROLES.get(user_role, {}).get("can_upload_docs"):
            return Response(
                {"error": "Insufficient permissions to upload documents."},
                status=403
            )

        file = request.FILES.get("file")
        if not file:
            return Response({"error": "No file provided"}, status=400)

        # Security validation (lazy import)
        from apps.agents.security_agent import SecurityAgent
        sec_result = SecurityAgent.validate_file_upload(
            file.name, file.size, file.content_type
        )
        if not sec_result.is_safe:
            return Response({"error": sec_result.rejection_message}, status=400)

        # Save file
        upload_dir = Path(settings.MEDIA_ROOT) / "documents"
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / f"{uuid.uuid4()}_{file.name}"

        with open(file_path, "wb+") as dest:
            for chunk in file.chunks():
                dest.write(chunk)

        # Save DB record
        doc = LabDocument.objects.create(
            title=request.data.get("title", file.name),
            file_name=file.name,
            file_path=str(file_path),
            document_type=request.data.get("document_type", "general"),
            uploaded_by=request.user,
            file_size=file.size,
            status="processing",
        )

        # Ingest into vector store
        try:
            doc_agent = get_doc_agent()
            result = doc_agent.ingest_document(
                str(file_path),
                metadata={
                    "doc_id": str(doc.id),
                    "title": doc.title,
                    "document_type": doc.document_type,
                    "uploaded_by": request.user.username,
                },
            )
            doc.status = "active"
            doc.chunks_count = result["chunks_created"]
            doc.save(update_fields=["status", "chunks_count"])

            audit_logger.info(
                f"DOCUMENT_UPLOAD | user={request.user.username} | "
                f"doc={doc.title} | chunks={result['chunks_created']}"
            )

            return Response({
                "document_id": str(doc.id),
                "title": doc.title,
                "chunks_created": result["chunks_created"],
                "status": "ingested",
            }, status=201)

        except Exception as e:
            doc.status = "failed"
            doc.save(update_fields=["status"])
            logger.error(f"Document ingestion failed: {e}", exc_info=True)
            return Response({"error": f"Document processing failed: {str(e)}"}, status=500)


class DocumentListView(APIView):
    """GET /api/v1/documents - List ingested documents."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        docs = LabDocument.objects.filter(status="active").values(
            "id", "title", "file_name", "document_type",
            "chunks_count", "created_at", "uploaded_by__username"
        )
        return Response({"documents": list(docs)})


class SourcesView(APIView):
    """GET /api/v1/sources - Knowledge base statistics."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        doc_agent = get_doc_agent()
        stats = doc_agent.get_collection_stats()
        doc_count = LabDocument.objects.filter(status="active").count()
        return Response({
            "document_count": doc_count,
            "vector_store": stats,
        })


class FeedbackView(APIView):
    """POST /api/v1/feedback - Submit message feedback."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        message_id = request.data.get("message_id")
        rating = request.data.get("rating")

        if not message_id or rating is None:
            return Response({"error": "message_id and rating required"}, status=400)

        try:
            message = Message.objects.get(id=message_id, session__user=request.user)
        except Message.DoesNotExist:
            return Response({"error": "Message not found"}, status=404)

        feedback, created = MessageFeedback.objects.update_or_create(
            message=message,
            defaults={
                "user": request.user,
                "rating": int(rating),
                "comment": request.data.get("comment", ""),
            }
        )

        return Response({"status": "feedback_recorded", "created": created})


class DeleteSessionView(APIView):
    """DELETE /api/v1/sessions/<session_id>/delete/ — delete a single session."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, session_id):
        try:
            session = ChatSession.objects.get(
                id=session_id, user=request.user
            )
            session_title = session.title
            session.delete()   # cascades to messages, workflows, feedback
            audit_logger.info(
                f"SESSION_DELETE | user={request.user.username} | "
                f"session={session_id} | title={session_title[:50]}"
            )
            return Response({"status": "deleted", "session_id": str(session_id)})
        except ChatSession.DoesNotExist:
            return Response({"error": "Session not found"}, status=404)


class DeleteAllSessionsView(APIView):
    """DELETE /api/v1/sessions/delete-all/ — delete all sessions for user."""
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        sessions = ChatSession.objects.filter(user=request.user)
        count = sessions.count()
        sessions.delete()
        audit_logger.info(
            f"SESSION_DELETE_ALL | user={request.user.username} | count={count}"
        )
        return Response({"status": "deleted", "deleted": count})


class HealthView(APIView):
    """GET /api/v1/health - System health check."""
    permission_classes = []  # Public endpoint

    def get(self, request):
        from django.conf import settings
        import requests as req

        health = {"status": "ok", "components": {}}

        # Check Ollama
        try:
            r = req.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            health["components"]["ollama"] = {"status": "ok", "models": models}
        except Exception as e:
            health["components"]["ollama"] = {"status": "error", "error": str(e)}
            health["status"] = "degraded"

        # Check database
        try:
            from django.db import connection
            connection.ensure_connection()
            health["components"]["database"] = {"status": "ok"}
        except Exception as e:
            health["components"]["database"] = {"status": "error", "error": str(e)}
            health["status"] = "degraded"

        # Check vector store
        doc_agent = get_doc_agent()
        vs_stats = doc_agent.get_collection_stats()
        health["components"]["vector_store"] = {
            "status": "ok" if "error" not in vs_stats else "error",
            **vs_stats
        }

        return Response(health)