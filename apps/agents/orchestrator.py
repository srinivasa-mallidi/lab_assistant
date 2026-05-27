"""
Orchestrator Agent
Central intelligence hub that detects intent and routes to sub-agents.
Uses the `ollama` Python library directly for reliability.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, AsyncGenerator, Tuple

import ollama as ollama_client

from django.conf import settings

logger = logging.getLogger("lab_assistant")


class IntentType(str, Enum):
    KNOWLEDGE = "knowledge"
    DATABASE  = "database"
    HYBRID    = "hybrid"
    GENERAL   = "general"


@dataclass
class AgentContext:
    """Shared context passed between agents."""
    user_id: int
    session_id: str
    user_role: str
    message: str
    conversation_history: list = field(default_factory=list)
    intent: IntentType = IntentType.GENERAL
    intent_confidence: float = 0.0
    rag_results: list = field(default_factory=list)
    db_results: Optional[dict] = None
    generated_sql: Optional[str] = None
    final_response: str = ""
    sources: list = field(default_factory=list)
    tokens_used: int = 0
    response_time_ms: int = 0
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


# ── Prompts ────────────────────────────────────────────────────────────────────

INTENT_PROMPT = """You are an intent classifier for a Laboratory LIMS chatbot.

Classify the user message into ONE category:
- knowledge  : questions about SOPs, procedures, training, how-to guides
- database   : requests for live LIMS data (pending samples, failed tests, approvals)
- hybrid     : needs BOTH documentation AND live data
- general    : greetings, thanks, general chat, help requests

User Message: {user_message}
Recent Context: {conversation_context}

Reply in EXACTLY this JSON (no extra text, no markdown):
{{"intent": "knowledge|database|hybrid|general", "confidence": 0.0-1.0, "reasoning": "brief"}}"""


SYNTHESIS_PROMPT = """You are LabAssist AI, an expert Laboratory Information Management System assistant.

USER ROLE: {user_role}

CONVERSATION HISTORY:
{conversation_history}

KNOWLEDGE BASE (SOPs/Manuals):
{rag_context}

LIVE DATABASE RESULTS:
{db_context}

USER QUESTION: {user_message}

Instructions:
- Answer precisely and professionally
- Reference SOP sections when applicable
- Present database results clearly with counts and key details
- For hybrid questions: procedural guidance first, then live data
- Never fabricate data; if context is missing, say so

RESPONSE:"""


def _get_model_name() -> str:
    """
    Get the Ollama model name.
    First checks SUPPORTED_MODELS dict, then uses OLLAMA_MODEL value directly.
    This means you can set OLLAMA_MODEL=qwen2:0.5b in .env and it just works.
    """
    model_key = settings.OLLAMA_DEFAULT_MODEL   # value from OLLAMA_MODEL in .env
    config = settings.SUPPORTED_MODELS.get(model_key)
    if config:
        return config["name"]
    # Not in the dict — use the value directly (e.g. "qwen2:0.5b", "tinyllama")
    return model_key


def _call_ollama(prompt: str, temperature: float = 0.1) -> str:
    """Call Ollama directly using the ollama Python library."""
    model = _get_model_name()
    response = ollama_client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": temperature},
    )
    return response["message"]["content"]


def _stream_ollama(prompt: str):
    """Stream tokens from Ollama."""
    model = _get_model_name()
    stream = ollama_client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1},
        stream=True,
    )
    for chunk in stream:
        token = chunk.get("message", {}).get("content", "")
        if token:
            yield token


class OrchestratorAgent:
    """
    Central orchestrator:
    1. Security check
    2. Intent classification
    3. Route to Document / Database agents
    4. Synthesize final response
    """

    def __init__(self):
        self._agents = {}

    @property
    def document_agent(self):
        if "document" not in self._agents:
            from apps.agents.document_agent import DocumentAgent
            self._agents["document"] = DocumentAgent()
        return self._agents["document"]

    @property
    def database_agent(self):
        if "database" not in self._agents:
            from apps.agents.database_agent import DatabaseAgent
            self._agents["database"] = DatabaseAgent()
        return self._agents["database"]

    @property
    def security_agent(self):
        if "security" not in self._agents:
            from apps.agents.security_agent import SecurityAgent
            self._agents["security"] = SecurityAgent()
        return self._agents["security"]

    def classify_intent(self, message: str, history: list) -> Tuple[IntentType, float]:
        recent = history[-3:] if len(history) > 3 else history
        context_str = "\n".join([
            f"{m.get('role','user').upper()}: {m.get('content','')[:200]}"
            for m in recent
        ]) or "No previous context"

        prompt = INTENT_PROMPT.format(
            user_message=message,
            conversation_context=context_str,
        )

        try:
            raw = _call_ollama(prompt, temperature=0.0)
            clean = raw.strip().replace("```json", "").replace("```", "").strip()
            # Extract JSON even if model adds surrounding text
            start = clean.find("{")
            end   = clean.rfind("}") + 1
            if start >= 0 and end > start:
                clean = clean[start:end]
            data = json.loads(clean)
            intent_str = data.get("intent", "general").lower()
            confidence = float(data.get("confidence", 0.7))
            intent = IntentType(intent_str) if intent_str in [e.value for e in IntentType] else IntentType.GENERAL
            logger.info(f"Intent: {intent} ({confidence:.2f}) — {data.get('reasoning','')}")
            return intent, confidence
        except Exception as e:
            logger.warning(f"Intent classification failed: {e}. Defaulting to GENERAL.")
            return IntentType.GENERAL, 0.5

    async def process(self, context: AgentContext) -> AgentContext:
        start_time = time.time()
        try:
            # 1. Security
            sec = self.security_agent.check(context)
            if not sec.is_safe:
                context.final_response = sec.rejection_message
                context.error = "SECURITY_BLOCK"
                return context

            # 2. Intent
            context.intent, context.intent_confidence = self.classify_intent(
                context.message, context.conversation_history
            )

            # 3. Route
            rag_context = "No relevant documentation found."
            db_context  = "No database query was executed."

            if context.intent in (IntentType.KNOWLEDGE, IntentType.HYBRID):
                rag_result = await self.document_agent.retrieve(context)
                context.rag_results = rag_result.chunks
                context.sources.extend(rag_result.sources)
                rag_context = rag_result.formatted_context or rag_context

            if context.intent in (IntentType.DATABASE, IntentType.HYBRID):
                db_result = await self.database_agent.query(context)
                context.db_results = db_result.data
                context.generated_sql = db_result.sql
                db_context = db_result.formatted_result or db_context

            # 4. Synthesize
            prompt = SYNTHESIS_PROMPT.format(
                user_message=context.message,
                rag_context=rag_context,
                db_context=db_context,
                conversation_history=self._format_history(context.conversation_history[-6:]),
                user_role=context.user_role,
            )

            context.final_response = _call_ollama(prompt, temperature=0.1)
            context.response_time_ms = int((time.time() - start_time) * 1000)

        except Exception as e:
            logger.error(f"Orchestrator error: {e}", exc_info=True)
            context.error = str(e)
            context.final_response = f"⚠️ Error: {e}\n\nPlease check the server logs."

        return context

    async def stream(self, context: AgentContext) -> AsyncGenerator[str, None]:
        sec = self.security_agent.check(context)
        if not sec.is_safe:
            yield sec.rejection_message
            return

        context.intent, _ = self.classify_intent(
            context.message, context.conversation_history
        )

        rag_context = "No relevant documentation found."
        db_context  = "No database query was executed."

        if context.intent in (IntentType.KNOWLEDGE, IntentType.HYBRID):
            rag_result = await self.document_agent.retrieve(context)
            context.rag_results = rag_result.chunks
            context.sources.extend(rag_result.sources)
            rag_context = rag_result.formatted_context or rag_context

        if context.intent in (IntentType.DATABASE, IntentType.HYBRID):
            db_result = await self.database_agent.query(context)
            context.db_results = db_result.data
            context.generated_sql = db_result.sql
            db_context = db_result.formatted_result or db_context

        prompt = SYNTHESIS_PROMPT.format(
            user_message=context.message,
            rag_context=rag_context,
            db_context=db_context,
            conversation_history=self._format_history(context.conversation_history[-6:]),
            user_role=context.user_role,
        )

        full_response = ""
        for token in _stream_ollama(prompt):
            full_response += token
            yield token

        context.final_response = full_response

    @staticmethod
    def _format_history(history: list) -> str:
        if not history:
            return "No previous conversation."
        return "\n".join([
            f"{m.get('role','user').capitalize()}: {m.get('content','')[:300]}"
            for m in history
        ])