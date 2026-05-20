"""Chan Master — AI-guided Socratic practice in the style of 'The Little Schemer'.

Uses the CompositeBackend pattern (StateBackend + FilesystemMiddleware)
for session persistence, with an LLM-powered guide that generates adaptive
multiple-choice questions and provides targeted feedback.
"""

from chan_master import ChanMaster
from models import (
    ChanTurn,
    Option,
    Question,
    SessionState,
    MasteryLevel,
)

__all__ = [
    "ChanMaster",
    "ChanTurn",
    "Option",
    "Question",
    "SessionState",
    "MasteryLevel",
]
