"""
WebSocket Consumer
Handles real-time streaming chat over WebSocket.
"""

import asyncio
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User

from apps.agents.orchestrator import OrchestratorAgent, AgentContext
from apps.chat.models import ChatSession, Message

logger = logging.getLogger("lab_assistant")

# Shared orchestrator instance
_orchestrator = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OrchestratorAgent()
    return _orchestrator


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for streaming chat responses."""

    async def connect(self):
        """Accept WebSocket connection (only authenticated users)."""
        if not self.scope["user"].is_authenticated:
            await self.close(code=4001)
            return

        self.user = self.scope["user"]
        self.session_id = self.scope["url_route"]["kwargs"].get("session_id")
        await self.accept()
        logger.info(f"WS connected: user={self.user.username}, session={self.session_id}")

    async def disconnect(self, close_code):
        logger.info(f"WS disconnected: user={self.user.username}, code={close_code}")

    async def receive(self, text_data):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(json.dumps({"error": "Invalid JSON"}))
            return

        message = data.get("message", "").strip()
        model = data.get("model", "llama3")

        if not message:
            await self.send(json.dumps({"error": "Empty message"}))
            return

        # Get or create session
        session = await self._get_or_create_session(model)

        # Get conversation history
        history = await self._get_history(session)

        # Save user message
        await self._save_message(session, "user", message)

        # Send "thinking" indicator
        await self.send(json.dumps({"type": "thinking", "status": True}))

        # Get user role
        user_role = await self._get_user_role()

        # Build context
        context = AgentContext(
            user_id=self.user.id,
            session_id=str(session.id),
            user_role=user_role,
            message=message,
            conversation_history=history,
        )

        # Stream response
        orch = get_orchestrator()
        full_response = ""

        try:
            async for chunk in orch.stream(context):
                full_response += chunk
                await self.send(json.dumps({
                    "type": "chunk",
                    "content": chunk,
                }))

            # Save assistant message
            saved_msg = await self._save_message(
                session, "assistant", full_response,
                intent=context.intent.value if context.intent else "general",
                sources=context.sources,
                sql=context.generated_sql,
            )

            # Send completion
            await self.send(json.dumps({
                "type": "done",
                "message_id": str(saved_msg.id),
                "session_id": str(session.id),
                "intent": context.intent.value if context.intent else "general",
                "sources": context.sources,
            }))

        except Exception as e:
            logger.error(f"WebSocket streaming error: {e}", exc_info=True)
            await self.send(json.dumps({
                "type": "error",
                "message": "An error occurred. Please try again.",
            }))

    @database_sync_to_async
    def _get_or_create_session(self, model: str) -> ChatSession:
        if self.session_id:
            try:
                return ChatSession.objects.get(
                    id=self.session_id,
                    user=self.user,
                    status=ChatSession.Status.ACTIVE
                )
            except ChatSession.DoesNotExist:
                pass

        return ChatSession.objects.create(
            user=self.user,
            title="New Conversation",
            model_used=model,
        )

    @database_sync_to_async
    def _get_history(self, session: ChatSession) -> list:
        msgs = session.get_recent_messages(limit=8)
        return [{"role": m.role, "content": m.content} for m in msgs]

    @database_sync_to_async
    def _save_message(
        self, session: ChatSession, role: str, content: str,
        intent: str = "general", sources: list = None, sql: str = None
    ) -> Message:
        return Message.objects.create(
            session=session,
            role=role,
            content=content,
            intent_type=intent,
            sources=sources or [],
            sql_query=sql,
        )

    @database_sync_to_async
    def _get_user_role(self) -> str:
        try:
            return self.user.userprofile.role
        except Exception:
            return "LAB_ANALYST"
