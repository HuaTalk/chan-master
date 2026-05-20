# Agent Guidelines for chan-master

This project implements Chan Master, a Socratic practice guide in the style of
*The Little Schemer*, powered by an LLM and local CompositeBackend persistence.

## Principles

- **One idea per question.** Each turn tests exactly one concept.
- **Concrete first.** Questions start with a specific example, not an abstract rule.
- **Build incrementally.** Question N+1 depends on an idea from question N.
- **Gentle correction.** Wrong answers get a brief reframe, not a lecture.
- **Mastery-driven.** The session ends when the learner demonstrates consistent understanding across enough variations.

## Architecture

| Layer | File | Role |
|---|---|---|
| Models | `models.py` | `Question`, `ChanTurn`, `SessionState` |
| Prompts | `prompts.py` | System prompt in *Little Schemer* style |
| Memory | `memory.py` | `CompositeBackend` (StateBackend + FilesystemMiddleware) + `SessionStore` |
| Engine | `chan_master.py` | `ChanMaster` — LLM call loop, answer evaluation, mastery heuristics |
| CLI | `cli.py` | Argument parsing, interactive topic selection, main loop |

## Extending

- **New topics** — add entries to `_PRESET_TOPICS` and `_TOPIC_ALIASES` in `cli.py`.
- **Custom mastery rules** — edit `_mastery_level()` in `chan_master.py`.
- **Changing the teaching style** — edit the `SYSTEM_PROMPT` in `prompts.py`.

## Testing

- **Local unit tests** — run `python -m pytest`.
- **Integration test** — run `python _integration_test.py`.
- The integration test resolves env config from `INTEGRATION_ENV_FILE`, then
  project-local `./.env`, then parent `../.env`.
- The resolved `.env` is loaded with override enabled, so real-LLM integration
  checks use the current `.env` values rather than inherited shell variables.
- **Feature completion** — after implementing any feature, run the local unit
  tests and the integration test with the current `.env`; if both pass,
  automatically create a git commit for the completed change.
- **No auto-commit without integration pass** — if the integration test fails,
  is skipped, hangs, times out, is manually stopped, or cannot run with the
  current `.env`, do not automatically commit. Report the verification status
  and wait for an explicit user instruction before committing.
