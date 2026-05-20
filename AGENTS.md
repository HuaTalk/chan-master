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

- **Integration smoke test** — run `python _smoke_test.py`.
- The smoke test resolves env config from `SMOKE_ENV_FILE`, then project-local
  `./.env`, then parent `../.env`.
- The resolved `.env` is loaded with override enabled, so real-LLM integration
  checks use the current `.env` values rather than inherited shell variables.
- **Feature completion** — after implementing any feature, run the integration
  smoke test with the current `.env`; if it passes, automatically create a git
  commit for the completed change.
