"""Memory persistence for tutoring sessions using the CompositeBackend pattern.

  - ``StateBackend`` — ephemeral, in-memory store (per-process cache).
  - ``FilesystemMiddleware`` — JSON-file persistence on disk.
  - ``CompositeBackend`` — two-tier cache (memory → filesystem).
"""

from __future__ import annotations

import datetime
import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from models import AnswerRecord, SessionState

# ---------------------------------------------------------------------------
# Pure-Python fallback implementing the deep-agents-memory protocol
# ---------------------------------------------------------------------------

DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "out"


class StateBackend:
    """Ephemeral in-memory key-value store."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def get(self, key: str) -> Optional[Any]:
        return self._data.get(key)

    async def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self._data

    async def keys(self, pattern: Optional[str] = None) -> list[str]:
        if pattern is None:
            return list(self._data.keys())
        return [k for k in self._data if pattern in k]


class FilesystemMiddleware:
    """Read/write serializable data to JSON files on disk."""

    def __init__(self, path: str | os.PathLike = ".") -> None:
        self._root = Path(path)
        self._root.mkdir(parents=True, exist_ok=True)

    async def write(self, key: str, value: Any) -> None:
        """Serialize *value* as JSON and write to ``{root}/{key}.json``."""
        path = self._path_for(key)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2))

    async def read(self, key: str) -> Optional[Any]:
        """Deserialize ``{root}/{key}.json`` or return ``None``."""
        path = self._path_for(key)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    async def delete(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)

    async def list_keys(self) -> list[str]:
        return sorted(p.stem for p in self._root.glob("*.json"))

    def _path_for(self, key: str) -> Path:
        # Sanitise key for filesystem
        safe = key.replace("/", "--").replace(":", "-")
        return self._root / f"{safe}.json"


class CompositeBackend:
    """Route reads through a cache hierarchy.

    Reads check *tier1* (fast) first, then fall back to *tier2* (slow).
    Writes go to both.
    """

    def __init__(self, tier1: StateBackend, tier2: FilesystemMiddleware) -> None:
        self._tier1 = tier1
        self._tier2 = tier2

    async def get(self, key: str) -> Optional[Any]:
        val = await self._tier1.get(key)
        if val is not None:
            return val
        val = await self._tier2.read(key)
        if val is not None:
            await self._tier1.set(key, val)
        return val

    async def set(self, key: str, value: Any) -> None:
        await self._tier1.set(key, value)
        await self._tier2.write(key, value)

    async def delete(self, key: str) -> None:
        await self._tier1.delete(key)
        await self._tier2.delete(key)

    async def list_sessions(self) -> list[str]:
        return await self._tier2.list_keys()


# ---------------------------------------------------------------------------
# High-level session store used by the tutor
# ---------------------------------------------------------------------------


class SessionStore:
    """Persist and resume tutoring sessions.

    Uses the deep-agents ``CompositeBackend`` pattern internally.
    """

    def __init__(self, out_dir: str | os.PathLike | None = None) -> None:
        resolved = out_dir or os.getenv("PRACTICE_OUT_DIR")
        self._out_dir = Path(resolved) if resolved else DEFAULT_OUT_DIR
        self._out_dir.mkdir(parents=True, exist_ok=True)

        fs = FilesystemMiddleware(self._out_dir)
        mem = StateBackend()
        self._cache = CompositeBackend(mem, fs)

    async def new_session(self, topic: str) -> SessionState:
        session = SessionState(
            session_id=_make_id(),
            topic=topic,
        )
        await self.save(session)
        return session

    async def save(self, state: SessionState) -> None:
        key = f"session:{state.session_id}"
        await self._cache.set(key, _to_dict(state))

    async def load(self, session_id: str) -> Optional[SessionState]:
        key = f"session:{session_id}"
        raw = await self._cache.get(key)
        if raw is None:
            return None
        return _from_dict(raw)

    async def list_sessions(self) -> list[SessionState]:
        keys = await self._cache.list_sessions()
        sessions: list[SessionState] = []
        for key in keys:
            raw = await self._cache.get(key)
            if raw is not None:
                sessions.append(_from_dict(raw))
        sessions.sort(key=lambda s: s.session_id, reverse=True)
        return sessions

    @property
    def out_dir(self) -> Path:
        return self._out_dir


def _make_id() -> str:
    now = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:21]
    return f"{now}-{uuid.uuid4().hex[:6]}"


def _to_dict(state: SessionState) -> dict:
    return {
        "session_id": state.session_id,
        "topic": state.topic,
        "turn_count": state.turn_count,
        "correct_count": state.correct_count,
        "total_questions": state.total_questions,
        "answers": [
            {
                "stem": a.stem,
                "chosen_keys": a.chosen_keys,
                "correct_keys": a.correct_keys,
                "is_correct": a.is_correct,
                "feedback": a.feedback,
            }
            for a in state.answers
        ],
        "completed": state.completed,
        "summary": state.summary,
    }


def _from_dict(d: dict) -> SessionState:
    answers: list[AnswerRecord] = []
    for a in d.get("answers", []):
        if isinstance(a, dict):
            answers.append(AnswerRecord(**a))
        elif isinstance(a, AnswerRecord):
            answers.append(a)
    return SessionState(
        session_id=d["session_id"],
        topic=d["topic"],
        turn_count=d.get("turn_count", 0),
        correct_count=d.get("correct_count", 0),
        total_questions=d.get("total_questions", 0),
        answers=answers,
        completed=d.get("completed", False),
        summary=d.get("summary"),
    )
