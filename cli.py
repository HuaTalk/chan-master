"""CLI interface for the Socratic practice-test agent.

Usage
-----
    python -m practice_test_agent
    python -m practice_test_agent --topic "binary search"
    python -m practice_test_agent --resume          # pick from recent sessions
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from memory import SessionStore
from tutor import SocraticTutor, preflight_llm

# ---------------------------------------------------------------------------
# Rich terminal helpers (zero-dependency ANSI subset)
# ---------------------------------------------------------------------------

_STYLE = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "red": "\033[91m",
    "cyan": "\033[96m",
    "magenta": "\033[95m",
    "reset": "\033[0m",
}


def _p(text: str, *styles: str) -> str:
    codes = "".join(_STYLE[s] for s in styles if s in _STYLE)
    return f"{codes}{text}{_STYLE['reset']}"


def _print_banner() -> None:
    print()
    print(_p("  ╔══════════════════════════════════════════╗", "cyan"))
    print(_p("  ║     Chan Master                          ║", "cyan"))
    print(_p("  ║     Socratic tutor · The Little Schemer  ║", "cyan"))
    print(_p("  ╚══════════════════════════════════════════╝", "cyan"))
    print()


def _print_turn(turn, mastery, turn_count: int) -> None:
    """Print a TutorTurn to the terminal."""
    if turn.feedback:
        # Color-code feedback
        if turn.is_correct is True:
            print(f"\n  {_p('✓', 'green')} {turn.feedback}")
        elif turn.is_correct is False:
            print(f"\n  {_p('✗', 'red')} {turn.feedback}")
        else:
            print(f"\n  {turn.feedback}")
        print()

    if turn.question:
        q = turn.question
        level_name, level_desc = mastery
        tag = _p(f"[{level_name.value}]", "dim")
        print(f"  {_p(f'─── Round {turn_count + 1}', 'bold')}  {tag}")
        print(f"  {_p(level_desc, 'dim')}")
        print()
        print(f"  {q.stem}")
        print()
        for opt in q.options:
            print(f"    {_p(opt.key, 'yellow')}) {opt.text}")
        print()

    if turn.session_complete and turn.summary:
        print(f"  {_p('═' * 50, 'cyan')}")
        print(f"  {_p('Session Complete!', 'bold', 'green')}")
        print()
        print(f"  {turn.summary}")
        print(f"  {_p('═' * 50, 'cyan')}")
        print()


# ---------------------------------------------------------------------------
# Topic selection
# ---------------------------------------------------------------------------

_PRESET_TOPICS = [
    ("binary-search", "Binary Search — invariant, halving, edge cases"),
    ("langgraph", "LangGraph — nodes, edges, state, checkpointing"),
    ("recursion", "Recursion — base case, call stack, tail recursion"),
    ("time-complexity", "Time Complexity — Big O, loops, recursion trees"),
    ("python-undo", "Python — lists vs tuples, mutability, references"),
]

_TOPIC_ALIASES: dict[str, str] = {
    "binary search": "binary-search",
    "binary": "binary-search",
    "langgraph": "langgraph",
    "lg": "langgraph",
    "recursion": "recursion",
    "recursive": "recursion",
    "time complexity": "time-complexity",
    "big o": "time-complexity",
    "complexity": "time-complexity",
    "python": "python-undo",
    "list": "python-undo",
    "tuple": "python-undo",
}


def _select_topic(args_topic: str | None) -> str:
    """Interactive topic selection."""
    if args_topic:
        return _TOPIC_ALIASES.get(args_topic.lower().strip(), args_topic.strip())

    print("  Choose a topic to practice:")
    print()
    for i, (key, desc) in enumerate(_PRESET_TOPICS, 1):
        print(f"    {_p(str(i), 'yellow')}) {desc}")
    print(f"    {_p('c', 'yellow')}) Custom topic (type your own)")
    print(f"    {_p('q', 'dim')}) Quit")
    print()

    while True:
        try:
            choice = input(f"  {_p('›', 'cyan')} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

        if choice in ("q", "quit", "exit"):
            sys.exit(0)

        if choice == "c":
            return input(f"  {_p('Enter topic:', 'cyan')} ").strip()

        if choice in _TOPIC_ALIASES:
            return _TOPIC_ALIASES[choice]

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(_PRESET_TOPICS):
                return _PRESET_TOPICS[idx][0]
        except ValueError:
            pass

        # Treat raw input as a custom topic
        if choice:
            return choice
        print(f"  {_p('Please choose a number or type a topic.', 'red')}")


def _select_resume_session(store: SessionStore) -> str | None:
    """Let the user pick a session to resume. Returns session_id or None."""
    sessions = asyncio.run(store.list_sessions())
    incomplete = [s for s in sessions if not s.completed][:10]
    if not incomplete:
        print(f"  {_p('No incomplete sessions found.', 'dim')}")
        return None

    print(f"  {_p('Recent incomplete sessions:', 'bold')}")
    print()
    for i, s in enumerate(incomplete, 1):
        acc = (s.correct_count / max(s.total_questions, 1)) * 100
        print(f"    {_p(str(i), 'yellow')}) {s.topic}  "
              f"({s.total_questions} Q, {acc:.0f}% correct)  "
              f"{_p(s.session_id[:20] + '…', 'dim')}")
    print()
    print(f"    {_p('0', 'dim')}) Start a new session instead")
    print()

    while True:
        try:
            choice = input(f"  {_p('›', 'cyan')} ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if choice == "0":
            return None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(incomplete):
                return incomplete[idx].session_id
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def _run_session(topic: str, resume_session_id: str | None = None) -> None:
    """Run the tutoring session loop."""
    store = SessionStore()

    if resume_session_id:
        session = await store.load(resume_session_id)
        if session is None:
            print(f"  {_p('Session not found. Starting fresh.', 'yellow')}")
            session = None
    else:
        session = None

    tutor = SocraticTutor(topic=topic, store=store, session=session)

    # --- First turn ---
    turn = await tutor.start()
    while True:
        _print_turn(turn, tutor.mastery, tutor.session.turn_count)

        if turn.session_complete:
            break

        # --- Get user input ---
        if turn.question:
            valid_keys = {o.key for o in turn.question.options}
            while True:
                try:
                    raw = input(f"  {_p('Your answer', 'cyan')} (e.g. A{', or comma-sep for multi-select' if len(turn.question.correct_keys) > 1 else ''}): ").strip()
                except (EOFError, KeyboardInterrupt):
                    print(f"\n  {_p('Session paused. Resume anytime!', 'dim')}")
                    return

                if raw.lower() in ("q", "quit", "exit"):
                    print(f"\n  {_p('Session saved. See you next time!', 'green')}")
                    return

                chosen = [k.strip().upper() for k in raw.replace(",", " ").split() if k.strip()]
                if chosen and all(k in valid_keys for k in chosen):
                    break
                valid_text = ", ".join(sorted(valid_keys))
                print(f"  {_p(f'Please pick from: {valid_text}', 'yellow')}")

            turn = await tutor.answer(chosen)

    # --- Session complete ---
    print()
    report = await tutor.generate_report_card()
    print(f"  {_p('Report Card', 'bold')}")
    print(f"  {report}")
    print()

    # Save final state
    await tutor.store.save(tutor.session)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chan Master — Socratic tutor in the style of The Little Schemer",
    )
    parser.add_argument(
        "--topic", "-t",
        help="Topic to practice (omit for interactive selection)",
    )
    parser.add_argument(
        "--resume", "-r",
        action="store_true",
        help="Resume an incomplete session",
    )
    parser.add_argument(
        "--list-sessions", "-l",
        action="store_true",
        help="List recent sessions",
    )
    args = parser.parse_args()

    # Load .env if present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    _print_banner()

    # Handle --list-sessions
    if args.list_sessions:
        store = SessionStore()
        sessions = asyncio.run(store.list_sessions())
        if not sessions:
            print(f"  {_p('No sessions yet.', 'dim')}")
            return
        print(f"  {_p(f'{len(sessions)} session(s):', 'bold')}")
        print()
        for s in sessions[:20]:
            status = _p("✓", "green") if s.completed else _p("…", "yellow")
            acc = (s.correct_count / max(s.total_questions, 1)) * 100
            print(f"  {status}  {s.topic:20s}  {s.session_id[:26]:26s}  "
                  f"{s.total_questions} Q  {acc:5.0f}%")
        return

    print(f"  {_p('Checking LLM availability...', 'dim')}")
    ok, probe_message = asyncio.run(preflight_llm())
    if not ok:
        print()
        print(f"  {_p('LLM 不可用，无法启动练习会话。', 'red')}")
        print(f"  {_p(probe_message, 'yellow')}")
        print()
        return

    # Resolve session
    resume_id = None
    if args.resume:
        store = SessionStore()
        resume_id = _select_resume_session(store)
        if resume_id is None and not args.topic:
            # Fall through to topic selection for a new session
            pass

    topic = _select_topic(args.topic)
    if not topic:
        print(f"  {_p('No topic selected. Goodbye!', 'dim')}")
        return

    asyncio.run(_run_session(topic, resume_session_id=resume_id))


if __name__ == "__main__":
    main()
