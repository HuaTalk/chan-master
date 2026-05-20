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

### Integration smoke test

```bash
python _smoke_test.py
```

The smoke test runs local checks first, then real LLM integration checks when a `.env` file is available. It resolves configuration in this order: `SMOKE_ENV_FILE`, project-local `./.env`, then parent `../.env`. The resolved `.env` is loaded with override enabled, so the integration test uses the current `.env` values even if the shell already has API or model variables set.

### Local unit tests

```bash
python -m pytest
```

The pytest suite is pure local: it uses fake async models, avoids real LLM calls, and exercises topic resolution, mastery heuristics, session persistence, and the buffered/non-buffered answer cycles.

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

## 中文说明

Chan Master 是一个小而美的 CLI-agent 应用。它的目标不是做一个完整教学平台，而是在终端里提供一个克制、连续、可恢复的练习体验：围绕一个主题，由 LLM 生成小步多选题，引导学习者通过回答、反馈和递进变体建立理解。

这个项目的核心定位是“练习型 agent”。它不是让模型一次性解释很多内容，而是让模型组织一条学习路径：从具体例子开始，每次只测试一个概念，答错时短反馈并降阶，答对后推进到下一个小变化，直到学习者表现出稳定掌握。

### 产品目标

- 启动简单：一个 Python CLI，不依赖 Web 服务或数据库。
- 交互轻量：只在终端中选择主题、答题、查看反馈。
- 节奏明确：一题一个概念，避免长篇讲解。
- 可恢复：session 本地保存，之后可以继续未完成练习。
- 可结束：通过 mastery heuristic 判断是否已经掌握，而不是无限聊天。
- 可扩展：新增主题、调整 prompt、修改掌握度规则都集中在少量文件中。

### 中文快速开始

```bash
cd chan-master
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

在 `.env` 中设置至少一个 API Key：

```bash
DEEPSEEK_API_KEY=your_key_here
# 或
OPENAI_API_KEY=your_key_here
```

启动应用：

```bash
python __main__.py
```

常用命令：

```bash
python __main__.py --topic "binary search"
python __main__.py --resume
python __main__.py --list-sessions
python __main__.py --topic "binary search" --buffer-question-num 5
```

### 设计原则

- **一个问题只测一个概念**：每轮只推进一个小知识点。
- **先具体后抽象**：优先用代码片段、列表、状态变化等具体例子发问。
- **递进而不是跳跃**：下一题应该依赖上一题刚建立的理解。
- **温和纠错**：答错时给短反馈，不写成长篇解释。
- **掌握后停止**：当正确率和连续答对情况足够稳定时结束 session。

### 架构概览

| 层 | 文件 | 作用 |
|---|---|---|
| Models | `models.py` | `Question`、`ChanTurn`、`SessionState` 等数据结构 |
| Prompts | `prompts.py` | Little Schemer 风格 system prompt 和辅助 prompt |
| Memory | `memory.py` | `CompositeBackend`、本地 JSON 持久化、`SessionStore` |
| Engine | `chan_master.py` | LLM 调用、答案评估、buffer、mastery heuristic |
| CLI | `cli.py` | 参数解析、选题、恢复 session、交互循环 |

### 工作流程

```text
1. CLI 加载 .env 并探测 LLM 可用性
2. 用户选择主题或恢复 session
3. ChanMaster 请求 LLM 生成 JSON 格式多选题
4. CLI 展示题目并读取用户答案
5. ChanMaster 评估答案、记录状态、生成反馈和下一题
6. SessionStore 将状态保存到 out/
7. 达到 mastered 或安全轮数上限后结束，并生成 report card
```

### 掌握度规则

当前规则刻意保持简单：

| 等级 | 条件 |
|---|---|
| `unknown` | 少于 2 题 |
| `seen` | 已接触主题，但正确率还不稳定 |
| `learning` | 正确率达到 75% |
| `stabilizing` | 最近 3 题连续答对 |
| `mastered` | 至少 5 题、正确率达到 75%、最近 3 题连续答对 |

### 存储方式

项目使用本地版 `CompositeBackend`：

- `StateBackend`：进程内缓存。
- `FilesystemMiddleware`：把 session 写入 JSON 文件。
- `CompositeBackend`：读时先查缓存，再查文件；写时同时写入两层。

默认持久化目录是 `./out`，也可以通过 `CHAN_MASTER_OUT_DIR` 修改。

### 适合继续优化的方向

- 使用更稳健的结构化输出，降低 LLM JSON 解析失败概率。
- 将本地单元测试和真实 LLM 集成烟测进一步拆开。
- 为每个 preset topic 定义更明确的概念阶梯。
- 让 buffer 模式的本地反馈更像真实教学反馈，而不只是显示正确答案。
- 增加 `pyproject.toml` 和 console script，让项目更像标准 Python CLI 包。
