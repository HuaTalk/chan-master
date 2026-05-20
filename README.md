# chan-master

**AI-powered Socratic practice** — in the style of *The Little Schemer*.

Practice tests are one of the most effective learning techniques ([Roediger & Karpicke, 2006](https://doi.org/10.1111/j.1751-228X.2006.tb00771.x)). Chan Master turns that insight into a CLI-based guided practice tool: it generates adaptive multiple-choice questions on any topic, evaluates your answers, and guides you step by step until you master the material.

## Philosophy

> *The Little Schemer* teaches one idea at a time. Each question builds on the last. Wrong answers get a gentle reframe, not a lecture. Right answers get a quick affirmation and the next — slightly harder — challenge.

Chan Master follows the same approach:

- **Concrete first.** Every question starts with a specific example: *"Consider the list [2, 5, 8, 12, 19]. What's the midpoint?"*
- **One idea per turn.** No compound questions. Master the invariant before discussing edge cases.
- **Build incrementally.** Question 2 depends on a concept from Question 1. By Question 10 you've constructed a full mental model.
- **Mastery-driven exit.** The session ends when you've demonstrated consistent understanding across enough variations.

## Quick start

```bash
cd chan-master
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # set DEEPSEEK_API_KEY or OPENAI_API_KEY

# Run from project directory
python __main__.py
```

## Usage

### Interactive session

```bash
python __main__.py       # from inside chan-master/
```

CLI 会在进入练习前自动探测一次 LLM 可用性；若 API Key / base URL / model 配置有误，会直接提示并退出。

### Topic directly

```bash
python __main__.py --topic "binary search"
```

### Question buffer

```bash
python __main__.py --topic "binary search" --buffer-question-num 5
python __main__.py --topic "binary search" --buffer-question-num 5 --buffer-refresh-percent 70
```

`--buffer-question-num` enables pre-generated questions so the next question can appear immediately after an answer. `--buffer-refresh-percent` defaults to `70`, meaning Chan Master starts replenishing the buffer once the remaining buffered questions are at or below 70% of the configured buffer size.

### Resume an incomplete session

```bash
python __main__.py --resume
```

### List past sessions

```bash
python __main__.py --list-sessions
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | DeepSeek API key (takes priority) |
| `OPENAI_API_KEY` | — | OpenAI API key (fallback) |
| `CHAN_MASTER_MODEL` | `deepseek-v4-pro` / `gpt-4.1-mini` | Model name (per-provider default) |
| `CHAN_MASTER_BASE_URL` | `https://api.deepseek.com/v1` | Custom API base URL |
| `CHAN_MASTER_OUT_DIR` | `./out` | Session persistence directory |

Chan Master auto-detects which provider to use: if `DEEPSEEK_API_KEY` is set it uses DeepSeek; otherwise it falls back to `OPENAI_API_KEY`.

## How it works

```
┌──────────────────────────────────────────────────────────┐
│  1. LLM generates MCQ in JSON (stem, options, answer)   │
│  2. CLI displays question, waits for user input          │
│  3. LLM evaluates answer, gives feedback,               │
│     generates next question                              │
│  4. Session state saved via CompositeBackend pattern     │
│     (CompositeBackend: StateBackend + FilesystemMiddleware) │
│  5. Repeats until mastery threshold reached or user quits│
└──────────────────────────────────────────────────────────┘
```

When buffering is enabled, the LLM pre-generates a queue of upcoming questions. Answers are checked locally against each question's `correct_keys`, immediate feedback is shown, and the buffer refreshes in the background when it reaches the configured threshold. With `--buffer-question-num 0`, Chan Master keeps the original per-turn LLM evaluation flow.

### Mastery heuristic

Chan Master tracks your accuracy and recent streak:

| Level | Condition |
|---|---|
| `unknown` | < 2 questions answered |
| `seen` | Exposed to concepts |
| `learning` | ≥ 75% accuracy |
| `stabilizing` | Last 3 consecutive correct |
| `mastered` | ≥ 75% + ≥ 5 questions + last 3 correct |

## Memory

Sessions are persisted using the **CompositeBackend** pattern:

- `StateBackend` — in-memory cache (per-process)
- `FilesystemMiddleware` — JSON files on disk (in `CHAN_MASTER_OUT_DIR` or `./out/`)
- `CompositeBackend` — reads check cache first, falls back to disk

## Project structure

```
chan-master/
├── __init__.py          # Package exports
├── __main__.py          # python -m entry
├── cli.py               # CLI: topic selection, main loop
├── chan_master.py       # ChanMaster engine
├── memory.py            # CompositeBackend persistence + SessionStore
├── models.py            # Data models (Question, ChanTurn, SessionState)
├── prompts.py           # LLM system prompts (Little Schemer style)
├── requirements.txt
├── README.md
├── AGENTS.md
└── .env.example
```

## Preset topics

- **Binary Search** — invariant, midpoint, halving, edge cases
- **LangGraph** — nodes, edges, state, checkpointing
- **Recursion** — base case, call stack, tail recursion
- **Time Complexity** — Big O, loops, recursion trees
- **Python** — lists vs tuples, mutability, references

Pick *Custom* from the menu to practice any other topic.
