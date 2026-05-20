import asyncio
from typing import Any

import pytest

from chan_master import ChanMaster, _mastery_level, _message_text
from chan_master.cli import _default_buffer_question_num, _default_buffer_refresh_percent, _select_topic
from chan_master.memory import SessionStore
from chan_master.models import AnswerRecord, MasteryLevel, SessionState


class FakeTurnModel:
    """Async chat model stub for non-buffered ChanMaster tests."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, _messages: list[Any]):
        self.calls += 1
        if self.calls == 1:
            content = """
            {
              "question": {
                "stem": "In [2, 5, 8], which value is at index 1?",
                "options": [
                  {"key": "A", "text": "2"},
                  {"key": "B", "text": "5"},
                  {"key": "C", "text": "8"}
                ],
                "correct_keys": ["B"]
              },
              "session_complete": false
            }
            """
        else:
            content = """
            {
              "feedback": "Yes. Index 1 points to the middle value, 5.",
              "is_correct": true,
              "question": {
                "stem": "If target 8 is greater than midpoint 5, where do we search?",
                "options": [
                  {"key": "A", "text": "left half"},
                  {"key": "B", "text": "right half"},
                  {"key": "C", "text": "stop"}
                ],
                "correct_keys": ["B"]
              },
              "session_complete": false
            }
            """
        return type("Resp", (), {"content": content})()


class FakeBufferModel:
    """Async chat model stub for buffered ChanMaster tests."""

    async def ainvoke(self, _messages: list[Any]):
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
              "stem": "Which side contains values greater than 5?",
              "options": [
                {"key": "A", "text": "left"},
                {"key": "B", "text": "right"},
                {"key": "C", "text": "neither"}
              ],
              "correct_keys": ["B"]
            },
            {
              "stem": "What is the next smaller search space?",
              "options": [
                {"key": "A", "text": "[2]"},
                {"key": "B", "text": "[8]"},
                {"key": "C", "text": "[2, 5]"}
              ],
              "correct_keys": ["B"]
            }
          ]
        }
        """


class FakeMalformedJsonModel:
    """Async chat model stub for common LLM JSON formatting mistakes."""

    async def ainvoke(self, _messages: list[Any]):
        return type("Resp", (), {"content": self._content()})()

    def _content(self) -> str:
        return r"""
        Here is the next turn:
        {not valid json}
        ```json
        {
          "question": {
            "stem": "In [2, 5, 8], which value is at index 1?",
            "options": "[{\"key\":\"A\",\"text\":\"2\"},{\"key\":\"B\",\"text\":\"5\"},{\"key\":\"C\",\"text\":\"8\"}]",
            "correct_keys": "B"
          },
          "feedback": null,
          "is_correct": null,
          "session_complete": false,
          "summary": null
        }
        ```
        {"ignored": true}
        """


def run(coro):
    return asyncio.run(coro)


def test_topic_selection_aliases_and_custom_topic():
    assert _select_topic("binary search") == "binary-search"
    assert _select_topic("Binary Search") == "binary-search"
    assert _select_topic("langgraph") == "langgraph"
    assert _select_topic("recursion") == "recursion"
    assert _select_topic("custom stuff") == "custom stuff"


def test_message_text_blocks_are_flattened():
    response = type(
        "Resp",
        (),
        {"content": [{"type": "text", "text": "{\"ok\": true}"}, {"type": "reasoning"}]},
    )()

    assert _message_text(response) == "{\"ok\": true}"


def test_mastery_heuristics_progression():
    state = SessionState(session_id="s", topic="binary search")
    level, _ = _mastery_level(state)
    assert level == MasteryLevel.UNKNOWN

    state.total_questions = 3
    state.correct_count = 1
    state.answers = [
        AnswerRecord("", ["A"], ["B"], False, ""),
        AnswerRecord("", ["B"], ["B"], True, ""),
        AnswerRecord("", ["A"], ["B"], False, ""),
    ]
    level, _ = _mastery_level(state)
    assert level == MasteryLevel.SEEN

    state.total_questions = 6
    state.correct_count = 6
    state.answers = [
        AnswerRecord("", ["A"], ["A"], True, "")
        for _ in range(6)
    ]
    level, _ = _mastery_level(state)
    assert level == MasteryLevel.MASTERED


def test_session_store_round_trip(tmp_path):
    async def scenario():
        store = SessionStore(out_dir=tmp_path)
        state = await store.new_session("binary search")
        state.total_questions = 5
        state.correct_count = 4
        state.answers.append(
            AnswerRecord(
                stem="Q1?",
                chosen_keys=["B"],
                correct_keys=["B"],
                is_correct=True,
                feedback="Good.",
            )
        )
        state.answers.append(
            AnswerRecord(
                stem="Q2?",
                chosen_keys=["A"],
                correct_keys=["B"],
                is_correct=False,
                feedback="Nope.",
            )
        )
        state.answers.append(
            AnswerRecord(
                stem="Q3?",
                chosen_keys=["B"],
                correct_keys=["B"],
                is_correct=True,
                feedback="Ok.",
            )
        )
        await store.save(state)

        loaded = await store.load(state.session_id)
        assert loaded is not None
        assert loaded.topic == "binary search"
        assert loaded.total_questions == 5
        assert loaded.correct_count == 4
        assert len(loaded.answers) == 3
        assert loaded.answers[0].is_correct is True
        assert loaded.answers[0].feedback == "Good."

    run(scenario())


def test_unbuffered_answer_cycle_uses_fake_model(tmp_path):
    async def scenario():
        model = FakeTurnModel()
        chan = ChanMaster(
            topic="binary search",
            model=model,
            store=SessionStore(out_dir=tmp_path),
        )

        first_turn = await chan.start()
        assert first_turn.question is not None
        assert first_turn.question.correct_keys == ["B"]

        next_turn = await chan.answer(["B"])
        assert next_turn.is_correct is True
        assert next_turn.feedback == "Yes. Index 1 points to the middle value, 5."
        assert next_turn.question is not None
        assert chan.session.total_questions == 1
        assert chan.session.correct_count == 1
        assert model.calls == 2

    run(scenario())


def test_buffered_answer_cycle_is_local_after_generation(tmp_path):
    async def scenario():
        chan = ChanMaster(
            topic="binary search",
            model=FakeBufferModel(),
            store=SessionStore(out_dir=tmp_path),
            buffer_question_num=3,
            buffer_refresh_percent=0,
        )

        first_turn = await chan.start()
        assert first_turn.question is not None
        assert len(chan._question_buffer) == 2

        next_turn = await chan.answer(["B"])
        assert next_turn.is_correct is True
        assert next_turn.feedback is not None
        assert "5 is the answer" in next_turn.feedback
        assert next_turn.question is not None
        assert chan.session.answers[-1].feedback == next_turn.feedback

    run(scenario())


def test_buffer_defaults_enable_buffering(monkeypatch):
    monkeypatch.delenv("CHAN_MASTER_BUFFER_QUESTION_NUM", raising=False)
    monkeypatch.delenv("CHAN_MASTER_BUFFER_REFRESH_PERCENT", raising=False)

    assert _default_buffer_question_num() == 5
    assert _default_buffer_refresh_percent() == 70


def test_buffer_defaults_can_be_configured(monkeypatch):
    monkeypatch.setenv("CHAN_MASTER_BUFFER_QUESTION_NUM", "0")
    monkeypatch.setenv("CHAN_MASTER_BUFFER_REFRESH_PERCENT", "90")

    assert _default_buffer_question_num() == 0
    assert _default_buffer_refresh_percent() == 90


def test_malformed_json_recovery_uses_first_valid_turn(tmp_path):
    async def scenario():
        chan = ChanMaster(
            topic="binary search",
            model=FakeMalformedJsonModel(),
            store=SessionStore(out_dir=tmp_path),
        )
        turn = await chan.start()

        assert turn.question is not None
        assert len(turn.question.options) == 3
        assert turn.question.options[1].key == "B"
        assert turn.question.correct_keys == ["B"]

    run(scenario())


def test_answer_before_start_raises(tmp_path):
    chan = ChanMaster(
        topic="binary search",
        model=FakeTurnModel(),
        store=SessionStore(out_dir=tmp_path),
    )

    with pytest.raises(RuntimeError, match="before any question"):
        run(chan.answer(["A"]))
