"""Socratic tutoring engine powered by an LLM.

Generates adaptive multiple-choice questions in *The Little Schemer* style,
evaluates answers, tracks progress, and decides when mastery is reached.
"""

from __future__ import annotations

import asyncio
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
    BUFFER_FEEDBACK_CORRECT,
    BUFFER_FEEDBACK_INCORRECT,
    BUFFER_QUESTIONS_PROMPT,
    BUFFER_REFRESH_PROMPT,
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
        buffer_question_num: int = 0,
        buffer_refresh_percent: int = 70,
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
        self.buffer_question_num = max(0, buffer_question_num)
        self.buffer_refresh_percent = min(100, max(0, buffer_refresh_percent))
        self._question_buffer: list[Question] = []
        self._refresh_task: Optional[asyncio.Task] = None
        self._refresh_error: Optional[BaseException] = None

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

        if self.buffer_enabled:
            await self._ensure_buffer(force=True)
            return self._turn_from_buffer()

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

        if self.buffer_enabled:
            self.session.answers[-1].feedback = self._buffer_feedback(last_q, chosen_keys, is_correct)
            turn = await self._next_buffered_turn(is_correct)
        else:
            # Get next turn from LLM
            turn = await self._next_turn()

        # Update the feedback for the record
        if turn.feedback and not self.buffer_enabled:
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

    @property
    def buffer_enabled(self) -> bool:
        """Whether the tutor should serve pre-generated questions."""
        return self.buffer_question_num > 0

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

    async def _next_buffered_turn(self, is_correct: bool) -> TutorTurn:
        """Return feedback plus the next pre-generated question."""
        feedback = self.session.answers[-1].feedback

        if self._should_complete():
            self._last_question = None
            return TutorTurn(
                feedback=feedback,
                is_correct=is_correct,
                session_complete=True,
                summary=(
                    f"You've completed {self.session.total_questions} questions "
                    f"({self.session.correct_count} correct). "
                    f"{self.mastery[1]}"
                ),
            )

        self._start_refresh_if_needed()

        if not self._question_buffer:
            await self._ensure_buffer(force=True)

        turn = self._turn_from_buffer()
        turn.feedback = feedback
        turn.is_correct = is_correct
        return turn

    def _turn_from_buffer(self) -> TutorTurn:
        """Pop the next buffered question and cache it as the current question."""
        if not self._question_buffer:
            raise RuntimeError("Question buffer is empty")
        question = self._question_buffer.pop(0)
        self._last_question = question
        self._start_refresh_if_needed()
        return TutorTurn(question=question)

    async def _ensure_buffer(self, force: bool = False) -> None:
        """Synchronously fill the question buffer when it is too small."""
        if self._refresh_task:
            try:
                await self._refresh_task
            finally:
                self._refresh_task = None
        if self._refresh_error:
            error = self._refresh_error
            self._refresh_error = None
            raise error

        if not force and len(self._question_buffer) > 0:
            return

        needed = self.buffer_question_num - len(self._question_buffer)
        if needed <= 0:
            return
        self._question_buffer.extend(await self._generate_buffer_questions(needed))

    def _start_refresh_if_needed(self) -> None:
        """Start a background refresh when the buffer reaches the threshold."""
        if not self.buffer_enabled or self._refresh_task or self._should_complete():
            return

        threshold = max(0, int(self.buffer_question_num * self.buffer_refresh_percent / 100))
        if len(self._question_buffer) > threshold:
            return

        needed = self.buffer_question_num - len(self._question_buffer)
        if needed <= 0:
            return

        self._refresh_task = asyncio.create_task(self._refresh_buffer(needed))

    async def _refresh_buffer(self, count: int) -> None:
        """Refresh the question buffer without blocking user input."""
        try:
            self._question_buffer.extend(await self._generate_buffer_questions(count))
        except BaseException as exc:
            self._refresh_error = exc
        finally:
            self._refresh_task = None

    async def _generate_buffer_questions(self, count: int) -> list[Question]:
        """Ask the LLM for upcoming questions only."""
        if count <= 0:
            return []

        prompt = self._buffer_prompt(count)
        response = await self.model.ainvoke([SystemMessage(content=prompt)])
        content = response.content if hasattr(response, "content") else str(response)
        raw = self._extract_json(content)
        questions = [self._parse_question(q) for q in raw.get("questions", [])]
        if not questions:
            raise ValueError(f"LLM output did not contain buffered questions:\n{content[:500]}")
        return questions[:count]

    def _buffer_prompt(self, count: int) -> str:
        """Build the prompt used to generate or refresh buffered questions."""
        mastery_level, mastery_desc = self.mastery
        kwargs = {
            "topic": self.topic,
            "count": count,
            "total_questions": self.session.total_questions,
            "correct_count": self.session.correct_count,
            "mastery_status": f"{mastery_level.value}: {mastery_desc}",
            "history": self._format_history() or "(no answered questions yet)",
        }
        if self._question_buffer:
            return BUFFER_REFRESH_PROMPT.format(
                **kwargs,
                buffered_questions=self._format_buffered_questions(),
            )
        return BUFFER_QUESTIONS_PROMPT.format(**kwargs)

    def _parse_question(self, raw: dict) -> Question:
        """Parse a dict into a ``Question``."""
        options = [Option(**o) for o in raw.get("options", [])]
        return Question(
            stem=raw["stem"],
            options=options,
            correct_keys=list(raw.get("correct_keys", [])),
        )

    def _buffer_feedback(self, question: Question, chosen_keys: list[str], is_correct: bool) -> str:
        """Create immediate local feedback for buffered mode."""
        correct_text = self._option_text(question, question.correct_keys)
        chosen_text = self._option_text(question, chosen_keys)
        if is_correct:
            explanation = f"{correct_text} is the answer."
            return BUFFER_FEEDBACK_CORRECT.format(explanation=explanation)
        explanation = f"You chose {chosen_text}; the answer is {correct_text}."
        return BUFFER_FEEDBACK_INCORRECT.format(explanation=explanation)

    def _option_text(self, question: Question, keys: list[str]) -> str:
        """Format selected option keys with their text."""
        by_key = {o.key: o.text for o in question.options}
        return ", ".join(f"{k}) {by_key.get(k, '')}".strip() for k in keys)

    def _should_complete(self) -> bool:
        """Apply completion heuristics without asking the LLM."""
        mastery_level, _ = self.mastery
        return mastery_level == MasteryLevel.MASTERED or self.session.turn_count >= _MAX_TURNS

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
            question = self._parse_question(q_raw)

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

    def _format_buffered_questions(self) -> str:
        """Format pending buffered questions for refresh prompts."""
        lines: list[str] = []
        for i, question in enumerate(self._question_buffer, 1):
            correct = ", ".join(question.correct_keys)
            lines.append(f"{i}. {question.stem}")
            lines.append(f"   Correct: {correct}")
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
