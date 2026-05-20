# chan-master

[English README](README.md)

Chan Master 是一个小而美的 CLI-agent 应用。它用 LLM 组织一场短小、连续、可恢复的练习：围绕一个主题，一次只问一个小问题，让学习者通过回答、反馈和递进变体真正掌握概念。

它不是刷题平台，也不是聊天式百科。它更像一个终端里的练习教练：少讲，常问；先给具体例子，再慢慢抽象。

## 适合什么场景

- 你想练一个概念，而不是读一篇长教程。
- 你希望模型不断追问小变体，确认你真的理解。
- 你偏好终端工具，不想启动 Web 应用。
- 你想保留练习记录，之后继续未完成的 session。

## 快速开始

```bash
cd chan-master
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
```

在 `.env` 中设置至少一个 API Key：

```bash
DEEPSEEK_API_KEY=your_key_here
# 或
OPENAI_API_KEY=your_key_here
```

启动：

```bash
chan-master
```

如果你没有激活项目虚拟环境，也可以在项目目录重新安装到当前 Python 环境：

```bash
python -m pip install -e .
```

## 常用命令

```bash
chan-master
chan-master --topic "binary search"
chan-master --resume
chan-master --list-sessions
chan-master --topic "binary search" --buffer-question-num 5
```

答题时输入选项即可，例如：

```text
B
```

多选题可以输入：

```text
A,C
```

输入 `q` 可以暂停，之后用 `chan-master --resume` 恢复。

## 产品原则

- **一个问题只测一个概念**：避免把多个知识点混在一起。
- **先具体后抽象**：用列表、代码片段、状态变化等具体例子开始。
- **递进而不是跳跃**：下一题依赖上一题建立的理解。
- **答错也继续前进**：短反馈、轻纠错，必要时换一个更小的问题。
- **掌握后停止**：根据正确率和连续答对情况结束 session。

## 预设主题

- `binary-search`：不变量、midpoint、区间收缩、边界情况
- `langgraph`：node、edge、state、checkpoint
- `recursion`：base case、调用栈、尾递归
- `time-complexity`：Big O、循环、递归树
- `python-undo`：list / tuple、可变性、引用

也可以直接输入任意自定义主题。

## 架构速览

| 层 | 文件 | 作用 |
|---|---|---|
| Models | `src/chan_master/models.py` | `Question`、`ChanTurn`、`SessionState` |
| Prompts | `src/chan_master/prompts.py` | 练习风格和 JSON 输出约束 |
| Memory | `src/chan_master/memory.py` | 本地 session 存储 |
| Engine | `src/chan_master/chan_master.py` | LLM 调用、答题循环、mastery 判断 |
| CLI | `src/chan_master/cli.py` | 参数解析、选题、交互主循环 |

运行流程：

```text
1. CLI 加载 .env 并探测 LLM
2. 用户选择主题或恢复 session
3. LLM 生成 JSON 格式多选题
4. 用户在终端答题
5. ChanMaster 记录答案并生成反馈
6. SessionStore 保存到 out/
7. 达到掌握条件后生成 report card
```

## 测试

本地单元测试不触发真实 LLM：

```bash
pytest -q
```

真实 LLM 集成测试：

```bash
python _integration_test.py
```

项目约定：如果集成测试失败、跳过、卡住、超时或被手动停止，不自动提交。

## 会话存储

默认会话保存在 `./out`。可以通过环境变量修改：

```bash
CHAN_MASTER_OUT_DIR=./my-sessions
```

存储实现是本地版 `CompositeBackend`：内存缓存 + 文件系统 JSON。

## 后续可优化方向

- 用更稳健的结构化输出替代普通 JSON 解析。
- 为每个预设主题设计更明确的概念阶梯。
- 改进 buffer 模式反馈，让它不仅指出正确答案，也给出简短推理。
- 增加更细的本地单元测试与真实 LLM 集成测试分层。
