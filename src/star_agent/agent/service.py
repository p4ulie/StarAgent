"""AgentService — builds the ADK agent and answers questions.

Wraps a single ADK ``LlmAgent`` + ``Runner`` (built once, reused across
requests) driving a **user-provided external llama.cpp server** through LiteLlm.
A concurrency semaphore + per-request timeout protect the shared LLM and keep
one slow generation from stalling callers (e.g. the Discord heartbeat).
"""

from __future__ import annotations

import asyncio
import logging

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from star_agent.agent import tools, uex_tools
from star_agent.agent.prompts import SYSTEM_INSTRUCTION
from star_agent.config import Settings, get_settings
from star_agent.rag.retriever import Retriever
from star_agent.rag.store import VectorStore

logger = logging.getLogger(__name__)

_APP_NAME = "star_agent"


class AgentService:
    """Answers Star Citizen questions via the ADK agent + RAG tool."""

    def __init__(
        self,
        settings: Settings,
        retriever: Retriever,
        max_concurrency: int = 4,
    ) -> None:
        tools.configure(retriever, settings.rag_results)
        uex_tools.configure(settings.uex_api_token)
        self._settings = settings
        self._agent = LlmAgent(
            name="star_agent",
            model=LiteLlm(
                # LiteLlm -> OpenAI-compatible server at LLM_BASE_URL.
                model=f"openai/{settings.llm_model}",
                api_base=settings.llm_base_url,
                # Real key for authenticated endpoints; local llama.cpp ignores
                # it but LiteLlm requires a non-empty value.
                api_key=settings.llm_api_key or "sk-none",
            ),
            instruction=SYSTEM_INSTRUCTION,
            tools=[tools.search_star_citizen_kb, *uex_tools.ALL_TOOLS],
        )
        self._session_service = InMemorySessionService()
        self._runner = Runner(
            agent=self._agent,
            app_name=_APP_NAME,
            session_service=self._session_service,
        )
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def _ensure_session(self, user_id: str, session_id: str) -> None:
        existing = await self._session_service.get_session(
            app_name=_APP_NAME, user_id=user_id, session_id=session_id
        )
        if existing is None:
            await self._session_service.create_session(
                app_name=_APP_NAME, user_id=user_id, session_id=session_id
            )

    async def _run(self, question: str, user_id: str, session_id: str) -> str:
        await self._ensure_session(user_id, session_id)
        message = types.Content(role="user", parts=[types.Part(text=question)])
        answer = ""
        async for event in self._runner.run_async(
            user_id=user_id, session_id=session_id, new_message=message
        ):
            if event.is_final_response() and event.content and event.content.parts:
                # Thinking models (e.g. Qwen3) return reasoning as parts marked
                # thought=True ahead of the real answer — keep only answer text.
                texts = [
                    p.text
                    for p in event.content.parts
                    if p.text and not getattr(p, "thought", False)
                ]
                if texts:
                    answer = "\n".join(texts)
        return answer

    async def answer(
        self,
        question: str,
        user_id: str = "anonymous",
        session_id: str | None = None,
    ) -> str:
        """Answer a question, grounded in the knowledge base.

        ``user_id``/``session_id`` scope conversation memory — map them to a
        Discord user/channel or an MCP client id for per-caller context.
        """
        session_id = session_id or user_id
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    self._run(question, user_id, session_id),
                    timeout=self._settings.llm_timeout,
                )
            except TimeoutError:
                logger.warning("Generation timed out after %ss", self._settings.llm_timeout)
                return (
                    "Sorry — that took too long to answer. Please try again or "
                    "rephrase your question."
                )


def build_agent_service(settings: Settings | None = None) -> AgentService:
    """Wire VectorStore -> Retriever -> AgentService from settings."""
    settings = settings or get_settings()
    store = VectorStore(settings)
    retriever = Retriever(store)
    return AgentService(settings, retriever)
