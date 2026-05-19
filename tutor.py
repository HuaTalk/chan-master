"""Socratic tutoring engine powered by an LLM.

Generates adaptive multiple-choice questions in *The Little Schemer* style,
evaluates answers, tracks progress, and decides when mastery is reached.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from memory import SessionState, SessionStore
from models import AnswerRecord, MasteryLevel, Option, Question, TutorTurn
from prompts import (
    REPORT_CARD_PROMPT,
    RESUME_PROMPT,
    SESSION_INTRO_PROMPT,
    SYSTEM_PROMPT,
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_MAX_TURNS = 30  # safety limit — force-complete after this many turns

# ---------------------------------------------------------------------------
# Mastery heuristics
# ---------------------------------------------------------------------------

_MASTERY_CORRECT_THRESHOLD = 0.75  # require ≥75 % accuracy
_MASTERY_MIN_QUESTIONS = 5         # at least this many questions asked
_MASTERY_STREAK = 3                # consecutive correct to consider "stabilizing"


def _mastery_level(state: SessionState) -> tuple[MasteryLevel, str]:
    """Estimate the learner's current mastery level from session state."""
    if state.total_questions < 2:
        return MasteryLevel.UNKNOWN, "Just starting."

    correct = state.correct_count
    total = state.total_questions
    acc = correct / max(total, 1)

    # Check recent streak
    recent = state.answers[-_MASTERY_STREAK:] if len(state.answers) >= _MASTERY_STREAK else state.answers
    streak = all(a.is_correct for a in recent)
    all_recent = len(recent) >= _MASTERY_STREAK

    if acc >= _MASTERY_CORRECT_THRESHOLD and total >= _MASTERY_MIN_QUESTIONS and streak and all_recent:
        return MasteryLevel.MASTERED, f"Strong understanding ({correct}/{total} correct, last {len(recent)} in a row)."
    if streak and all_recent:
        return MasteryLevel.STABILIZING, f"On a roll ({correct}/{total} correct, last {len(recent)} correct)."
    if acc >= _MASTERY_CORRECT_THRESHOLD:
        return MasteryLevel.LEARNING, f"Getting there ({correct}/{total} correct)."
    return MasteryLevel.SEEN, f"Still building ({correct}/{total} correct)."


# ---------------------------------------------------------------------------
# Tutor
# ---------------------------------------------------------------------------


class SocraticTutor:
    """LLM-powered Socratic tutor for a single topic session."""

    def __init__(
        self,
        topic: str,
        model: Optional[BaseChatModel] = None,
        store: Optional[SessionStore] = None,
        session: Optional[SessionState] = None,
    ) -> None:
        self.topic = topic
        self.model = model or _default_model()
        self.store = store or SessionStore()
        self.session = session or SessionState(
            session_id="",
            topic=topic,
        )
        self._messages: list = []  # full conversation (LLM message list)
        self._last_question: Optional[Question] = None  # cached for answer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> TutorTurn:
        """Begin or resume a tutoring session.

        Returns the first ``TutorTurn`` with a question.
        """
        if not self.session.session_id:
            self.session = await self.store.new_session(self.topic)

        # Build initial message list
        if self.session.total_questions == 0:
            self._messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                SystemMessage(content=SESSION_INTRO_PROMPT.format(topic=self.topic)),
            ]
        else:
            history = self._format_history()
            self._messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                SystemMessage(
                    content=RESUME_PROMPT.format(
                        topic=self.topic,
                        total_questions=self.session.total_questions,
                        correct_count=self.session.correct_count,
                        history=history,
                    )
                ),
            ]

        return await self._next_turn()

    async def answer(self, chosen_keys: list[str]) -> TutorTurn:
        """Submit the learner's answer and get the next ``TutorTurn``.

        The tutor evaluates the answer, appends feedback, and either
        presents the next question or ends the session.
        """
        # Record the last question context
        last_q = self._last_question
        if last_q is None:
            raise RuntimeError("answer() called before any question was asked")

        is_correct = sorted(chosen_keys) == sorted(last_q.correct_keys)

        # Append user's answer to conversation
        answer_text = ", ".join(chosen_keys)
        self._messages.append(HumanMessage(content=answer_text))

        # Record in session state
        record = AnswerRecord(
            stem=last_q.stem,
            chosen_keys=chosen_keys,
            correct_keys=last_q.correct_keys,
            is_correct=is_correct,
            feedback="",  # filled below after LLM responds
        )
        self.session.answers.append(record)
        self.session.total_questions += 1
        if is_correct:
            self.session.correct_count += 1
        self.session.turn_count += 1

        # Get next turn from LLM
        turn = await self._next_turn()

        # Update the feedback for the record
        if turn.feedback:
            self.session.answers[-1].feedback = turn.feedback

        # Handle session completion
        if turn.session_complete and turn.summary:
            self.session.completed = True
            self.session.summary = turn.summary

        await self.store.save(self.session)
        return turn

    @property
    def mastery(self) -> tuple[MasteryLevel, str]:
        return _mastery_level(self.session)

    async def generate_report_card(self) -> str:
        """Generate a natural-language report card for the session."""
        total = self.session.total_questions
        correct = self.session.correct_count
        pct = (correct / max(total, 1)) * 100
        prompt = REPORT_CARD_PROMPT.format(
            total_questions=total,
            correct_count=correct,
            pct=pct,
        )
        resp = await self.model.ainvoke([SystemMessage(content=prompt)])
        return resp.content if hasattr(resp, "content") else str(resp)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _next_turn(self) -> TutorTurn:
        """Call the LLM and parse the structured response into a TutorTurn.

        If the session has exceeded ``_MAX_TURNS`` the tutor force-completes
        with a summary rather than making another LLM call.
        """
        if self.session.turn_count >= _MAX_TURNS:
            return TutorTurn(
                session_complete=True,
                summary=(
                    f"You've completed {self.session.total_questions} questions "
                    f"({self.session.correct_count} correct). "
                    "That's a solid practice session — come back anytime to reinforce further!"
                ),
            )

        response = await self.model.ainvoke(self._messages)
        content = response.content if hasattr(response, "content") else str(response)
        self._messages.append(AIMessage(content=content))

        raw = self._extract_json(content)
        turn = self._parse_turn(raw)

        # Cache the last question so answer() can reference it
        if turn.question:
            self._last_question = turn.question
        else:
            self._last_question = None

        return turn

    def _extract_json(self, text: str) -> dict:
        """Extract the first JSON object from *text*."""
        match = _JSON_RE.search(text)
        if not match:
            msg = f"LLM output did not contain JSON:\n{text[:500]}"
            raise ValueError(msg)
        return json.loads(match.group())

    def _parse_turn(self, raw: dict) -> TutorTurn:
        """Parse a dict into a ``TutorTurn``."""
        q_raw = raw.get("question")
        question = None
        if q_raw:
            options = [Option(**o) for o in q_raw.get("options", [])]
            question = Question(
                stem=q_raw["stem"],
                options=options,
                correct_keys=list(q_raw.get("correct_keys", [])),
            )

        return TutorTurn(
            question=question,
            feedback=raw.get("feedback"),
            is_correct=raw.get("is_correct"),
            session_complete=raw.get("session_complete", False),
            summary=raw.get("summary"),
        )

    def _format_history(self) -> str:
        """Format the conversation history for the resume prompt."""
        lines: list[str] = []
        for a in self.session.answers:
            chosen = ", ".join(a.chosen_keys)
            correct = ", ".join(a.correct_keys)
            marker = "✓" if a.is_correct else "✗"
            lines.append(f"Q: {a.stem}")
            lines.append(f"  Answer: {chosen} (correct: {correct}) {marker}")
            if a.feedback:
                lines.append(f"  Tutor: {a.feedback}")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODEL_CACHE: dict[str, BaseChatModel] = {}

_DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
_DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


def _default_model() -> BaseChatModel:
    """Build a ChatOpenAI instance, preferring DeepSeek if its key is set.

    Resolution order (highest priority first):
      1. ``DEEPSEEK_API_KEY``          → DeepSeek at ``DEEPSEEK_BASE_URL``
      2. ``OPENAI_API_KEY``             → OpenAI
      3. No key set at all              → raises ``ValueError``

    The model name comes from ``PRACTICE_MODEL`` (default depends on provider).
    The API base URL can be overridden via ``PRACTICE_BASE_URL``.
    """
    # Resolve model name
    model_name = os.getenv("PRACTICE_MODEL", "").strip()

    # Resolve provider
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()

    if deepseek_key:
        base_url = (os.getenv("PRACTICE_BASE_URL") or _DEEPSEEK_BASE_URL).rstrip("/")
        model = model_name or _DEFAULT_DEEPSEEK_MODEL
        cache_key = f"deepseek:{model}:{base_url}"
        if cache_key not in _MODEL_CACHE:
            _MODEL_CACHE[cache_key] = ChatOpenAI(
                model=model,
                api_key=deepseek_key,
                base_url=base_url,
            )
        return _MODEL_CACHE[cache_key]

    if openai_key:
        base_url = os.getenv("PRACTICE_BASE_URL", "").strip() or None
        model = model_name or _DEFAULT_OPENAI_MODEL
        cache_key = f"openai:{model}:{base_url or 'default'}"
        if cache_key not in _MODEL_CACHE:
            _MODEL_CACHE[cache_key] = ChatOpenAI(
                model=model,
                api_key=openai_key,
                base_url=base_url,
            )
        return _MODEL_CACHE[cache_key]

    raise ValueError(
        "No API key found. Set DEEPSEEK_API_KEY or OPENAI_API_KEY in your .env file."
    )


def llm_config_guide() -> str:
    """Return a short, user-facing guide for LLM configuration."""
    return (
        "请先配置 LLM 后再启动：\n"
        "  1) 在项目根目录创建并填写 .env（可参考 .env.example）\n"
        "  2) 至少设置一个 API Key：DEEPSEEK_API_KEY 或 OPENAI_API_KEY\n"
        "  3) 如有代理/网关，检查 PRACTICE_BASE_URL 与 PRACTICE_MODEL 是否正确"
    )


async def preflight_llm() -> tuple[bool, str]:
    """Probe whether the configured LLM is usable before starting a session."""
    try:
        model = _default_model()
    except Exception as exc:  # pragma: no cover - defensive branch
        return False, f"{llm_config_guide()}\n\n配置错误详情: {exc}"

    try:
        # Lightweight real call: validates key/base_url/model/network availability.
        await model.ainvoke(
            [
                SystemMessage(content="Return a one-word reply."),
                HumanMessage(content="ok"),
            ]
        )
    except Exception as exc:
        return False, f"{llm_config_guide()}\n\n连通性错误详情: {exc}"

    model_name = getattr(model, "model_name", getattr(model, "model", "unknown"))
    return True, str(model_name)
