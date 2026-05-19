# Agent Guidelines for practice-test-agent

This submodule implements a Socratic practice-test tutor in the style of
*The Little Schemer*, powered by an LLM and the deep-agents-memory pattern.

## Principles

- **One idea per question.** Each turn tests exactly one concept.
- **Concrete first.** Questions start with a specific example, not an abstract rule.
- **Build incrementally.** Question N+1 depends on an idea from question N.
- **Gentle correction.** Wrong answers get a brief reframe, not a lecture.
- **Mastery-driven.** The session ends when the learner demonstrates consistent understanding across enough variations.

## Architecture

| Layer | File | Role |
|---|---|---|
| Models | `models.py` | `Question`, `TutorTurn`, `SessionState` |
| Prompts | `prompts.py` | System prompt in *Little Schemer* style |
| Memory | `memory.py` | deep-agents-compatible `CompositeBackend` (StateBackend + FilesystemMiddleware) + `SessionStore` |
| Engine | `tutor.py` | `SocraticTutor` — LLM call loop, answer evaluation, mastery heuristics |
| CLI | `cli.py` | Argument parsing, interactive topic selection, main loop |

## Extending

- **New topics** — add entries to `_PRESET_TOPICS` and `_TOPIC_ALIASES` in `cli.py`.
- **Custom mastery rules** — edit `_mastery_level()` in `tutor.py`.
- **Changing the teaching style** — edit the `SYSTEM_PROMPT` in `prompts.py`.
