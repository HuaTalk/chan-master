#!/usr/bin/env python3
"""Smoke test — runs the full tutoring pipeline against the real LLM.

Tests: model init, question generation, answer evaluation, session
persistence, mastery heuristics, report card, and CLI argument parsing.
Run with real API credentials from .env.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from tutor import SocraticTutor, _mastery_level, _default_model
from memory import SessionStore
from models import (
    AnswerRecord,
    MasteryLevel,
    SessionState,
)
from cli import _select_topic


class FakeBufferModel:
    """Small async model stub for buffered-mode tests."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, _messages: list[Any]):
        self.calls += 1
        return type("Resp", (), {"content": self._content()})()

    def _content(self) -> str:
        return """
        {
          "questions": [
            {
              "stem": "In [2, 5, 8], which value is at index 1?",
              "options": [
                {"key": "A", "text": "2"},
                {"key": "B", "text": "5"},
                {"key": "C", "text": "8"}
              ],
              "correct_keys": ["B"]
            },
            {
              "stem": "In [2, 5, 8], which side contains values greater than 5?",
              "options": [
                {"key": "A", "text": "left"},
                {"key": "B", "text": "right"},
                {"key": "C", "text": "neither"}
              ],
              "correct_keys": ["B"]
            },
            {
              "stem": "If target 8 is greater than midpoint 5, where should we search?",
              "options": [
                {"key": "A", "text": "left half"},
                {"key": "B", "text": "right half"},
                {"key": "C", "text": "stop immediately"}
              ],
              "correct_keys": ["B"]
            }
          ]
        }
        """


def _resolve_env_file() -> Path:
    """Resolve the env file path used for real-LLM smoke testing.

    Priority:
      1) SMOKE_ENV_FILE (explicit override)
      2) ./.env (project local)
      3) ../.env (monorepo parent)
    """
    explicit = os.getenv("SMOKE_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    root = Path(__file__).resolve().parent
    local = root / ".env"
    if local.exists():
        return local

    parent = root.parent / ".env"
    if parent.exists():
        return parent

    return local


def _load_smoke_env() -> tuple[bool, str]:
    """Load env and validate at least one API key for real LLM smoke tests."""
    env_path = _resolve_env_file()
    if not env_path.exists():
        return False, (
            "Missing .env for real-LLM smoke test. "
            "Create ./ .env (or set SMOKE_ENV_FILE) with DEEPSEEK_API_KEY/OPENAI_API_KEY."
        )

    load_dotenv(dotenv_path=env_path)
    if os.getenv("DEEPSEEK_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip():
        return True, f"Loaded env: {env_path}"

    return False, (
        f"Loaded env but no API key found: {env_path}. "
        "Set DEEPSEEK_API_KEY or OPENAI_API_KEY."
    )


# ---------------------------------------------------------------------------
# Tests using the real DeepSeek V4 Pro model
# ---------------------------------------------------------------------------

async def test_model_init():
    """Verify the real model can be instantiated."""
    model = _default_model()
    assert model is not None
    model_name = getattr(model, "model_name", getattr(model, "model", "?"))
    print(f"  ✅ test_model_init (model={model_name})")


async def test_question_generation():
    """Verify the tutor generates a parseable question from the real LLM."""
    tutor = SocraticTutor(topic="binary search")
    turn = await tutor.start()

    assert turn.question is not None, "No question generated"
    assert len(turn.question.options) >= 2, f"Too few options ({len(turn.question.options)})"
    assert len(turn.question.correct_keys) >= 1, "No correct keys"
    assert not turn.session_complete

    print(f"  ✅ test_question_generation")
    print(f"     Q: {turn.question.stem[:80]}…")
    print(f"     Options: {len(turn.question.options)}, Correct: {turn.question.correct_keys}")


async def test_correct_answer_cycle():
    """One full correct answer cycle: question → answer → feedback → next question."""
    tutor = SocraticTutor(topic="binary search")
    turn1 = await tutor.start()
    assert turn1.question is not None

    # Answer correctly
    correct = list(turn1.question.correct_keys)
    turn2 = await tutor.answer(correct)

    assert turn2.feedback is not None, "No feedback received"
    assert turn2.is_correct is True, f"Expected correct, got is_correct={turn2.is_correct}"
    assert not turn2.session_complete, "Session ended too early"

    print(f"  ✅ test_correct_answer_cycle")
    print(f"     Feedback: {turn2.feedback[:80]}…")
    print(f"     Mastery: {tutor.mastery[0].value}")


async def test_wrong_answer_cycle():
    """Answer wrong → feedback + still continues."""
    tutor = SocraticTutor(topic="binary search")
    turn1 = await tutor.start()
    assert turn1.question is not None

    # Pick the first *wrong* answer
    correct = set(turn1.question.correct_keys)
    wrong_keys = [o.key for o in turn1.question.options if o.key not in correct]
    assert wrong_keys, "No wrong option to pick (all options correct)"
    wrong_key = wrong_keys[0]

    turn2 = await tutor.answer([wrong_key])

    assert turn2.feedback is not None, "No feedback on wrong answer"
    assert turn2.is_correct is False, f"Expected wrong, got is_correct={turn2.is_correct}"
    assert not turn2.session_complete, "Session ended on first wrong answer"
    assert tutor.session.correct_count == 0
    assert tutor.session.total_questions == 1

    print(f"  ✅ test_wrong_answer_cycle")
    print(f"     Feedback: {turn2.feedback[:80]}…")


async def test_session_persistence():
    """Verify session save/load round-trip (no LLM needed)."""
    store = SessionStore(out_dir="/tmp/pt-smoke-real")
    s = await store.new_session("binary search")
    s.total_questions = 5
    s.correct_count = 4
    s.answers.append(AnswerRecord(stem="Q1?", chosen_keys=["B"], correct_keys=["B"], is_correct=True, feedback="Good"))
    s.answers.append(AnswerRecord(stem="Q2?", chosen_keys=["A"], correct_keys=["B"], is_correct=False, feedback="Nope"))
    s.answers.append(AnswerRecord(stem="Q3?", chosen_keys=["B"], correct_keys=["B"], is_correct=True, feedback="Ok"))
    await store.save(s)

    loaded = await store.load(s.session_id)
    assert loaded is not None
    assert loaded.topic == "binary search"
    assert loaded.total_questions == 5
    assert loaded.correct_count == 4
    assert len(loaded.answers) == 3
    assert loaded.answers[0].is_correct is True

    import shutil
    shutil.rmtree("/tmp/pt-smoke-real", ignore_errors=True)
    print("  ✅ test_session_persistence")


async def test_buffered_answer_cycle():
    """Buffered mode answers immediately from pre-generated questions."""
    tutor = SocraticTutor(
        topic="binary search",
        model=FakeBufferModel(),
        store=SessionStore(out_dir="/tmp/pt-smoke-buffer"),
        buffer_question_num=3,
        buffer_refresh_percent=0,
    )
    turn1 = await tutor.start()
    assert turn1.question is not None
    assert len(tutor._question_buffer) == 2

    turn2 = await tutor.answer(list(turn1.question.correct_keys))
    assert turn2.feedback is not None
    assert turn2.is_correct is True
    assert turn2.question is not None
    assert tutor.session.total_questions == 1
    assert tutor.session.answers[-1].feedback == turn2.feedback

    import shutil
    shutil.rmtree("/tmp/pt-smoke-buffer", ignore_errors=True)
    print("  ✅ test_buffered_answer_cycle")


async def test_mastery_heuristics():
    """Verify mastery level progression (no LLM needed)."""
    s0 = SessionState(session_id="t", topic="t")
    ml, _ = _mastery_level(s0)
    assert ml == MasteryLevel.UNKNOWN

    s1 = SessionState(session_id="t", topic="t", total_questions=3, correct_count=1)
    for _ in range(3):
        s1.answers.append(AnswerRecord(stem="", chosen_keys=["A"], correct_keys=["B"], is_correct=False, feedback=""))
    ml, _ = _mastery_level(s1)
    assert ml == MasteryLevel.SEEN

    s2 = SessionState(session_id="t", topic="t", total_questions=6, correct_count=6)
    for _ in range(6):
        s2.answers.append(AnswerRecord(stem="", chosen_keys=["A"], correct_keys=["A"], is_correct=True, feedback=""))
    ml, _ = _mastery_level(s2)
    assert ml == MasteryLevel.MASTERED

    print("  ✅ test_mastery_heuristics")


def test_topic_selection():
    """Verify CLI topic resolution (no LLM needed)."""
    assert _select_topic("binary search") == "binary-search"
    assert _select_topic("Binary Search") == "binary-search"
    assert _select_topic("langgraph") == "langgraph"
    assert _select_topic("recursion") == "recursion"
    assert _select_topic("custom stuff") == "custom stuff"
    print("  ✅ test_topic_selection")


async def test_report_card():
    """Verify report card generation from real LLM."""
    tutor = SocraticTutor(topic="binary search")
    # Simulate some history
    turn = await tutor.start()
    await tutor.answer(list(turn.question.correct_keys))

    report = await tutor.generate_report_card()
    assert report is not None
    assert len(report) > 20

    print(f"  ✅ test_report_card")
    print(f"     Report: {report[:100]}…")


async def main():
    print("=" * 56)
    print("  Smoke Tests: practice_test_agent (REAL LLM)")
    print("=" * 56)
    print()

    test_topic_selection()
    await test_session_persistence()
    await test_buffered_answer_cycle()
    await test_mastery_heuristics()

    ok_env, env_msg = _load_smoke_env()
    if not ok_env:
        print(f"  ⚠ {env_msg}")
        print("  Skip real-LLM smoke tests.")
        return
    print(f"  ✅ {env_msg}")

    await test_model_init()
    await test_question_generation()
    await test_correct_answer_cycle()
    await test_wrong_answer_cycle()
    print(f"\n  (waiting for report card — requires extra LLM call)")
    await test_report_card()

    print()
    print("=" * 56)
    print("  ✅ ALL SMOKE TESTS PASSED")
    print("=" * 56)


if __name__ == "__main__":
    asyncio.run(main())
