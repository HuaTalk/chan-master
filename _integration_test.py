#!/usr/bin/env python3
"""Integration test: runs Chan Master against the configured real LLM.

Tests: model init, question generation, answer evaluation, and report card.
Run with real API credentials from .env or INTEGRATION_ENV_FILE.
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from chan_master import ChanMaster, _default_model


def _resolve_env_file() -> Path:
    """Resolve the env file path used for real-LLM integration testing.

    Priority:
      1) INTEGRATION_ENV_FILE (explicit override)
      2) ./.env (project local)
      3) ../.env (monorepo parent)
    """
    explicit = os.getenv("INTEGRATION_ENV_FILE", "").strip()
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


def _load_integration_env() -> tuple[bool, str]:
    """Load env and validate at least one API key for real LLM integration tests.

    Integration tests intentionally let the resolved .env override any inherited
    shell variables so each run uses the current checked configuration.
    """
    env_path = _resolve_env_file()
    if not env_path.exists():
        return False, (
            "Missing .env for real-LLM integration test. "
            "Create ./.env (or set INTEGRATION_ENV_FILE) with DEEPSEEK_API_KEY/OPENAI_API_KEY."
        )

    load_dotenv(dotenv_path=env_path, override=True)
    if os.getenv("DEEPSEEK_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip():
        return True, f"Loaded env: {env_path}"

    return False, (
        f"Loaded env but no API key found: {env_path}. "
        "Set DEEPSEEK_API_KEY or OPENAI_API_KEY."
    )


# ---------------------------------------------------------------------------
# Tests using the configured real LLM
# ---------------------------------------------------------------------------

async def check_model_init():
    """Verify the real model can be instantiated."""
    model = _default_model()
    assert model is not None
    model_name = getattr(model, "model_name", getattr(model, "model", "?"))
    print(f"  ✅ check_model_init (model={model_name})")


async def check_question_generation():
    """Verify Chan Master generates a parseable question from the real LLM."""
    chan = ChanMaster(topic="binary search")
    turn = await chan.start()

    assert turn.question is not None, "No question generated"
    assert len(turn.question.options) >= 2, f"Too few options ({len(turn.question.options)})"
    assert len(turn.question.correct_keys) >= 1, "No correct keys"
    assert not turn.session_complete

    print(f"  ✅ check_question_generation")
    print(f"     Q: {turn.question.stem[:80]}…")
    print(f"     Options: {len(turn.question.options)}, Correct: {turn.question.correct_keys}")


async def check_correct_answer_cycle():
    """One full correct answer cycle: question → answer → feedback → next question."""
    chan = ChanMaster(topic="binary search")
    turn1 = await chan.start()
    assert turn1.question is not None

    # Answer correctly
    correct = list(turn1.question.correct_keys)
    turn2 = await chan.answer(correct)

    assert turn2.feedback is not None, "No feedback received"
    assert turn2.is_correct is True, f"Expected correct, got is_correct={turn2.is_correct}"
    assert not turn2.session_complete, "Session ended too early"

    print(f"  ✅ check_correct_answer_cycle")
    print(f"     Feedback: {turn2.feedback[:80]}…")
    print(f"     Mastery: {chan.mastery[0].value}")


async def check_wrong_answer_cycle():
    """Answer wrong → feedback + still continues."""
    chan = ChanMaster(topic="binary search")
    turn1 = await chan.start()
    assert turn1.question is not None

    # Pick the first *wrong* answer
    correct = set(turn1.question.correct_keys)
    wrong_keys = [o.key for o in turn1.question.options if o.key not in correct]
    assert wrong_keys, "No wrong option to pick (all options correct)"
    wrong_key = wrong_keys[0]

    turn2 = await chan.answer([wrong_key])

    assert turn2.feedback is not None, "No feedback on wrong answer"
    assert turn2.is_correct is False, f"Expected wrong, got is_correct={turn2.is_correct}"
    assert not turn2.session_complete, "Session ended on first wrong answer"
    assert chan.session.correct_count == 0
    assert chan.session.total_questions == 1

    print(f"  ✅ check_wrong_answer_cycle")
    print(f"     Feedback: {turn2.feedback[:80]}…")


async def check_report_card():
    """Verify report card generation from real LLM."""
    chan = ChanMaster(topic="binary search")
    # Simulate some history
    turn = await chan.start()
    await chan.answer(list(turn.question.correct_keys))

    report = await chan.generate_report_card()
    assert report is not None
    assert len(report) > 20

    print(f"  ✅ check_report_card")
    print(f"     Report: {report[:100]}…")


async def main():
    print("=" * 56)
    print("  Integration Tests: chan-master (REAL LLM)")
    print("=" * 56)
    print()

    ok_env, env_msg = _load_integration_env()
    if not ok_env:
        print(f"  ⚠ {env_msg}")
        print("  Skip real-LLM integration tests.")
        return
    print(f"  ✅ {env_msg}")

    await check_model_init()
    await check_question_generation()
    await check_correct_answer_cycle()
    await check_wrong_answer_cycle()
    print(f"\n  (waiting for report card — requires extra LLM call)")
    await check_report_card()

    print()
    print("=" * 56)
    print("  ✅ ALL INTEGRATION TESTS PASSED")
    print("=" * 56)


if __name__ == "__main__":
    asyncio.run(main())
