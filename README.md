<div align="center">

# ask-jev

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-blue.svg?style=flat-square" alt="License: GPL-3.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/Dependencies-Zero-16a34a.svg?style=flat-square" alt="Zero Dependencies" />
  <img src="https://img.shields.io/badge/Latency-%3C280ms-ea580c.svg?style=flat-square" alt="Latency: <280ms" />
  <img src="https://img.shields.io/badge/Design-Fail--Open-7c3aed.svg?style=flat-square" alt="Fail-Open" />
  <img src="https://img.shields.io/badge/Evidence-Verbatim_LF-0d9488.svg?style=flat-square" alt="Verbatim LF" />
  <a href="https://logicrw.github.io/awesome-jev-projects/en/"><img src="https://img.shields.io/badge/Awesome%20Jev-Radar-d7fa91?style=flat-square&labelColor=1a201a" alt="Awesome Jev" /></a>
</p>

<p align="center">
  <b>Bounded advisory decisions and verbatim extractive reading view for AI coding agents and CLI pipelines.</b>
  <br>
  面向 AI 编程智能体与命令行管道的有界决策与原文提纯工具。
</p>

<p align="center">
  <a href="#english"><b>English</b></a> &nbsp;•&nbsp; <a href="#中文"><b>简体中文</b></a> &nbsp;•&nbsp; <a href="https://logicrw.github.io/awesome-jev-projects/en/"><b>Awesome Jev ↗</b></a>
</p>

> [!NOTE]
> **System-1 Cognitive Layer**: `ask-jev` is built as a fast, fail-open advisory filter for coding agents (Claude Code, Codex, Antigravity) — delegating micro-decisions and verbatim extraction without stalling execution loops.

</div>

---

<a name="english"></a>
## English

### Overview

When building autonomous coding agents (Claude Code, Codex, Antigravity, OpenClaw, Maestro) or automated CI pipelines, delegating every minor branching decision to a heavy reasoning model introduces seconds of latency, token waste, and context drift. Conversely, naive regex heuristics are brittle and lack semantic understanding.

`ask-jev` is a lightweight, fail-open CLI utility and Agent Skill for closed-set choices, evidence verification, and verbatim text purification. It operates with a strict 280ms deadline and zero external dependencies.

---

### System 1 (Advisory) vs. System 2 (Reasoning LLMs)

| Dimension | System 2 (Reasoning LLMs) | ask-jev (System 1 Advisory) |
| :--- | :--- | :--- |
| **Latency** | 1,500ms – 10,000ms+ (Slow) | **< 280ms hard deadline** (DNS, TLS, body, reap) |
| **Output Contract** | Freeform text / Markdown / Fragile JSON | **Typed JSON** (`schema: ask-jev.v1`) |
| **Context Extraction** | Generative summary (paraphrased, hallucination risk) | **Verbatim physical LF lines** (AST & syntax preserved) |
| **Failure Behavior** | Crash, prompt injection, hanging timeout | **Fail-open (exit 0)**, full original text fallback |
| **Dependencies** | Bulky SDKs, background threads, external packages | **Zero external dependencies** (Python 3.10+ stdlib) |
| **Attack Surface** | Background daemons, open loopback ports | **Daemonless CLI** (`O_NOFOLLOW`, private-key filter) |

---

### Community Findings & Design Decisions

Recent community experiments across GitHub (*NousResearch/Hermes, Winnow, fast-jev-compaction, typesafe-mcp, Pi, Prism, SemDecide*) revealed several practical failure modes in early Jev integrations. Here is how `ask-jev` handles them:

1. **Narrative vs. Execution Evidence (*fast-jev #65*)**
   - *Problem*: Aggressive context compression stripped raw tool errors and exit codes while keeping model chit-chat, causing agents to hallucinate completion for 9 consecutive turns.
   - *Design*: `split_units()` encloses complete Python modules, fenced blocks, git diff hunks, and critical error tokens (`Traceback`, `exit code`, `returncode`, `assert`, `panic`, `Error:`). Execution evidence is never stripped from the narrative.

2. **Self-Referential Confirmation Bias (*typesafe-mcp #13*)**
   - *Problem*: Agents prompted Jev with statements like "Obviously P0" and received a 0.99 confidence confirmation that developers treated as independent verification.
   - *Design*: Jev output is strictly advisory. `choose` requires both confidence $\ge 0.85$ and winner probability $\ge 0.85$. `check` returns `true` at $\ge 0.85$, `false` at $\le 0.15$, and `null` for intermediate values. Prompts carry neutral observations only.

3. **SDK Retries & Hanging Deadlocks**
   - *Problem*: Upstream SDKs defaulted to 2 retries, 500ms backoff, and 10–30s timeouts. In high-frequency agent loops, delayed responses stalled multi-agent coordination.
   - *Design*: Single request with a hard 280ms wall deadline covering DNS, TLS, headers, and body read. Process group `SIGKILL` on expiration. Any network or provider error (401/402/429) exits 0 with a clean fallback.

4. **Sidecar Daemon Security Surface (*Winnow #1*)**
   - *Problem*: Running a local background HTTP sidecar without authentication or CORS allowed malicious web scripts to drain quotas or access context.
   - *Design*: Zero background daemons, zero open ports. Executed strictly on-demand via standard UNIX pipes and stdin. Path traversal is blocked using `O_DIRECTORY | O_NOFOLLOW`. Payloads containing private keys (`BEGIN PRIVATE KEY`) or bearer tokens are dropped before reaching the network.

5. **Semantic Misalignment & State Fitting (*fast-jev #52*)**
   - *Problem*: Asking whether evidence was "non-reproducible" wiped entire task contexts. Pre-pruning text before passing it to the model compounded the issue.
   - *Design*: Prompts focus strictly on task continuity: *"What evidence or constraints are required to continue correctly?"* Candidate text remains visible in full during judgment.

6. **Payload Validation (*typesafe-mcp #15 / fast-jev #29*)**
   - *Problem*: JavaScript float64 precision loss with integers $> 2^{53}$, silent truncations on oversized responses, and unhandled `NaN` values.
   - *Design*: Enforces strict bounds: input $\le 256\text{ KiB}$, request $\le 96\text{ KiB}$, response $\le 32\text{ KiB}$. Validates finite probabilities ($0.0 \le p \le 1.0$) and rejects `NaN`, `inf`, and booleans.

---

### CLI Modes & Examples

#### 1. `choose`: Closed-Set Classification
Categorizes text into 2–12 explicit options.

```bash
printf '%s\n' 'Fix typo in install command' | \
  python3 scripts/ask_jev.py choose \
    --question 'Which category fits best?' \
    --option 'docs' \
    --option 'bugfix' \
    --option 'feature'
```

Output:
```json
{
  "schema": "ask-jev.v1",
  "mode": "choose",
  "status": "ok",
  "reason": "decisive",
  "answer": "docs",
  "judgment": {
    "choice": "docs",
    "confidence": 0.96,
    "probabilities": {"docs": 0.96, "bugfix": 0.03, "feature": 0.01}
  },
  "advisory": true,
  "receipt": "/path/to/receipt.json",
  "evidence_path": "/path/to/source.txt"
}
```

#### 2. `check`: Evidence Assertion
Verifies whether the provided text factually supports a claim.

```bash
git log -1 --stat | \
  python3 scripts/ask_jev.py check \
    --question 'Does this commit include database migrations?'
```

Output:
```json
{
  "schema": "ask-jev.v1",
  "mode": "check",
  "status": "ok",
  "reason": "decisive",
  "answer": false,
  "judgment": 0.04,
  "advisory": true,
  "receipt": "/path/to/receipt.json",
  "evidence_path": "/path/to/source.txt"
}
```

#### 3. `purify`: Verbatim Extractive View
Selects relevant physical line spans from verbose logs while preserving byte-for-byte fidelity.

```bash
cat build.log | \
  python3 scripts/ask_jev.py purify \
    --query 'Compiler errors, tracebacks, and failed assertions'
```

Output:
```json
{
  "schema": "ask-jev.v1",
  "mode": "purify",
  "status": "ok",
  "reason": "verbatim_selection",
  "original_available": true,
  "spans": [{"start": 42, "end": 68}],
  "text": "Traceback (most recent call last):\n  File \"app.py\", line 12, in <module>\n..."
}
```

---

### Agent Skill Integration

`ask-jev` includes a standard [SKILL.md](SKILL.md) for coding agents.

```bash
# Clone directly into your agent skills directory
git clone https://github.com/logicrw/ask-jev.git ~/.agents/skills/ask-jev
chmod +x ~/.agents/skills/ask-jev/scripts/ask_jev.py
```

When an agent needs to prune a 150 KiB log:
```bash
python3 ~/.agents/skills/ask-jev/scripts/ask_jev.py purify \
  --query 'Error causes and failing tests' \
  --input-file test.log
```
If credentials are not configured or the network is unreachable, `ask-jev` automatically emits the entire original input without failing the agent.

---

### Environment Variables

| Variable | Required | Description |
| :--- | :---: | :--- |
| `TYPESAFE_API_KEY` | Yes (for remote) | API key for the underlying provider. |
| `HARNESS_JEV_ALLOW_REMOTE` | Yes (for remote) | Explicit consent gate (`1` or `true`). |
| `JEV_MODEL` | No | Model override (defaults to standard fast model). |
| `HARNESS_JEV_EVIDENCE_DIR` | No | Local directory for raw evidence and receipts. |

---

### Test Suite

The test suite runs completely offline with 100% mocked transport:

```bash
pytest -v
```

```
147 passed in 6.64s
```

---

<a name="中文"></a>
## 中文

### 项目概述

在构建自主编程智能体（Claude Code、Codex、Antigravity、OpenClaw 等）或自动化 CI/CD 流程时，如果将每一个微小的分支判断都派发给重型推理大模型，会引入数秒的响应延迟、额外的 Token 消耗以及上下文偏移。纯正则规则虽然快速，但往往难以应对灵活的语义判断。

`ask-jev` 是一个面向命令行管道与智能体的辅助工具，用于闭集分类、事实支撑度校验与原文结构提纯。工具执行受限于 280ms 硬时限，采用纯 Python 标准库实现，且具备全链路 Fail-Open 降级能力。

---

### 机制对比：System 1（辅助判断）vs. System 2（推理大模型）

| 维度 | System 2（推理大模型） | ask-jev（System 1 辅助判断） |
| :--- | :--- | :--- |
| **响应耗时** | 1,500ms – 10,000ms+（慢速阻塞） | **硬性 < 280ms**（包含 DNS、TLS、Body 及进程回收） |
| **输出契约** | 非结构化文本 / Markdown / 正则解析 JSON | **强类型 JSON 契约**（`schema: ask-jev.v1`） |
| **内容提取** | 生成式摘要（容易漏掉行号、改写语句） | **物理 LF 真实行**（保留完整 AST 与语法结构） |
| **异常处理** | 任务崩溃、超时挂起、输出格式混乱 | **全链路 Fail-Open（Exit 0）**，降级输出全部原文字节 |
| **外部依赖** | 复杂 SDK、后台异步线程、额外三方包 | **零外部依赖**（纯 Python 3.10+ 标准库） |
| **攻击暴露面** | 本地常驻后台服务、开放本地端口 | **无守护进程 CLI**（支持 `O_NOFOLLOW` 与私钥过滤） |

---

### 社区实战经验与设计取舍

梳理 GitHub 社区（*NousResearch/Hermes, Winnow, fast-jev-compaction, typesafe-mcp, Pi, Prism, SemDecide*）在 Jev 早期应用中的实测反馈，我们针对性地确立了以下工程规范：

1. **避免“保留叙述、删掉报错”导致的虚假完成（*fast-jev #65*）**
   - *现象*：部分上下文压缩实现删除了底层工具的报错输出与退出码，却保留了智能体的对话叙述，导致智能体误以为已完成任务，连续 9 轮未调用工具发生幻觉。
   - *解法*：`split_units()` 将 Python AST 模块、代码块、Git Diff 与关键报错标识（`Traceback`、`exit code`、`returncode`、`assert`、`panic`、`Error:`）做结构化整体保留，不破坏执行证据。

2. **避免诱导模型确认调用者自我结论（*typesafe-mcp #13*）**
   - *现象*：智能体在上下文中写入“明显是 P0 级别问题”，再向 Jev 发起确认提问，得到 0.99 的高置信度回复，开发者误将其作为客观验证。
   - *解法*：Jev 输出严格保持 Advisory（参考性质）。`choose` 要求置信度 $\ge 0.85$ 且获胜项概率 $\ge 0.85$；`check` 在 $0.15 \sim 0.85$ 区间一律输出 `unknown`（`answer: null`）。提问仅承载中立事实。

3. **终结 SDK 递归重试与尾延迟挂起**
   - *现象*：官方 SDK 默认 2 次重试、500ms 退避与 10~30 秒超时，在多智能体密集调用时容易因网络抖动引起级联阻塞。
   - *解法*：单次请求硬限 280ms，涵盖 DNS 解析、TLS 握手及完整响应接收。超时通过 POSIX 进程组直接发送 `SIGKILL` 回收。发生网络或状态码异常（401/402/429）时均以 Exit 0 退出并触发原生降级。

4. **拒绝本地 Sidecar 带来的安全暴露面（*Winnow #1*）**
   - *现象*：为减少冷启动开销而运行本地未鉴权 HTTP 服务，因缺少 Origin 和 Content-Type 校验，容易被本地网页或恶意脚本利用盗刷。
   - *解法*：不开启常驻后台服务，不占用本地端口。全部交互通过标准输入输出及命令行管道完成。读取文件时使用 `O_DIRECTORY | O_NOFOLLOW` 防范软链接逃逸；正则检测到私钥（`BEGIN PRIVATE KEY`）或 Bearer Token 时自动拦截网络发送。

5. **校正语义度量与提示词错位（*fast-jev #52*）**
   - *现象*：把“材料是否绝对不可重新获取”当作判断准则，加上判定前对上下文的有损截断，导致关键任务信息被清空。
   - *解法*：题面聚焦于任务延续性：*“继续正确完成当前任务所需的证据或约束是什么”*。候选材料完整随问题发送，不在判定前预先截断。

6. **严格的数据与载荷校验（*typesafe-mcp #15 / fast-jev #29*）**
   - *现象*：浮点精度损失（$> 2^{53}$）、大包响应静默截断却返回成功，以及未校验的 `NaN` 渗入逻辑。
   - *解法*：输入限制 $\le 256\text{ KiB}$，请求 $\le 96\text{ KiB}$，响应 $\le 32\text{ KiB}$。强制校验浮点数为合法概率区间（$0.0 \le p \le 1.0$），遇到 `NaN`、`inf` 或布尔混用时严格降级。

---

### 工作模式与调用示例

#### 1. `choose`：闭集分类
在 2~12 个明确选项中做出语义判断。

```bash
printf '%s\n' '修复安装命令中的拼写错误' | \
  python3 scripts/ask_jev.py choose \
    --question '属于哪个分类？' \
    --option 'docs' \
    --option 'bugfix' \
    --option 'feature'
```

#### 2. `check`：事实支撑度断言
判断提供的上下文是否支撑特定陈述。

```bash
git log -1 --stat | \
  python3 scripts/ask_jev.py check \
    --question '该提交是否包含数据库迁移？'
```

#### 3. `purify`：原文保真提纯
提取符合查询条件的真实代码块或报错片段，不修改原文字符与换行。

```bash
cat build.log | \
  python3 scripts/ask_jev.py purify \
    --query '编译错误与断言失败'
```

---

### Agent 技能集成

项目根目录包含标准 [SKILL.md](SKILL.md) 描述文件：

```bash
git clone https://github.com/logicrw/ask-jev.git ~/.agents/skills/ask-jev
chmod +x ~/.agents/skills/ask-jev/scripts/ask_jev.py
```

在智能体处理长日志时调用：
```bash
python3 ~/.agents/skills/ask-jev/scripts/ask_jev.py purify \
  --query '错误原因及失败用例' \
  --input-file test.log
```
未配置 API Key 或网络不可达时，工具将原样输出全部文本，不中断主流程。

---

### 环境变量说明

| 变量名 | 是否必填 | 说明 |
| :--- | :---: | :--- |
| `TYPESAFE_API_KEY` | 仅远程调用必填 | 服务端 API 访问密钥。 |
| `HARNESS_JEV_ALLOW_REMOTE` | 仅远程调用必填 | 明确的外发授权开关（`1` 或 `true`）。 |
| `JEV_MODEL` | 否 | 自定义模型标识符。 |
| `HARNESS_JEV_EVIDENCE_DIR` | 否 | 证据与执行凭证本地保存目录。 |

---

### 离线测试套件

测试套件采用纯 Mock 方式验证，无需访问外部网络：

```bash
pytest -v
```

```
147 passed in 6.64s
```

---

### 许可证 (License)

本项目采用 **GNU General Public License v3.0 or later (GPL-3.0-or-later)** 许可证。
详情见 [LICENSE](LICENSE)。

Copyright (C) 2026 logicrw.
