# ask-jev

<p align="center">
  <img src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg" alt="License: GPL-3.0" />
  <img src="https://img.shields.io/badge/python-3.10%2B-brightgreen.svg" alt="Python: 3.10+" />
  <img src="https://img.shields.io/badge/dependencies-zero-success.svg" alt="Zero External Dependencies" />
  <img src="https://img.shields.io/badge/latency-bounded_%3C280ms-orange.svg" alt="Latency: <280ms" />
  <img src="https://img.shields.io/badge/design-fail--open-blueviolet.svg" alt="Fail-Open Architecture" />
  <img src="https://img.shields.io/badge/evidence-verbatim_LF-teal.svg" alt="Verbatim Evidence" />
</p>

<p align="center">
  <strong>Ultra-fast, fail-open advisory decisions and verbatim extractive reading view for AI coding agents and CLI pipelines.</strong><br>
  <em>面向 AI 编程智能体与命令行管道的高性能、防虚构、毫秒级 Fail-Open 决策与原文提纯引擎。</em>
</p>

<p align="center">
  <a href="#english">English Documentation</a> • <a href="#chinese">中文深度文档</a>
</p>

---

<a name="english"></a>
# English Documentation

## ⚡ The Dilemma: Heavy LLMs vs. Fragile Heuristics

When autonomous coding agents (Claude Code, Codex, Antigravity, OpenClaw, Maestro) or automated CI/CD pipelines execute tasks, they constantly face **micro-decisions**:
- *Routing*: Does this issue need a docs fix, a refactor, or a unit test?
- *Verification*: Does this command output factually prove the bug is resolved?
- *Context Pruning*: How do we extract only the failing traceback from a 200 KiB log without losing lines or inventing text?

Calling a full 70B+ frontier LLM for every minor decision causes **3–15 second latency bottlenecks**, massive token costs, and prompt drift. Conversely, naive regex heuristics are brittle and lack semantic understanding.

`ask-jev` delivers a **deterministic, fail-open advisory cognitive layer**: sub-280ms speed, zero external dependencies, and strict byte-for-byte evidence preservation.

---

## 🔬 What Real-World JEV Research Revealed & How `ask-jev` Solves It

Recent independent community investigations across GitHub and production forks (*NousResearch/Hermes, Winnow, fast-jev-compaction, typesafe-mcp, Pi, Prism, SemDecide*) exposed several critical traps in early JEV implementations.

`ask-jev` was engineered specifically to counter these 6 failure modes:

| # | Community Failure Mode in the Wild | Real-World Incident / Evidence | How `ask-jev` Surgically Solves It |
|---|---|---|---|
| **1** | **Narrative Illusion & Evidence Stripping** | *fast-jev #65*: Compaction stripped raw tool errors and exit codes while keeping LLM text, causing agents to hallucinate completion for 9 consecutive loops. | **AST & Syntax Structural Pinning**: `split_units()` encloses complete Python modules, fenced blocks, git diff hunks, and critical error anchors (`exit code`, `Traceback`, `fatal`). Execution evidence is never stripped from narrative. |
| **2** | **Self-Referential Confirmation Bias** | *typesafe-mcp PR #13*: Agents injected "Obviously P0" into the prompt, receiving a 0.99 confidence echo that developers mistook for independent verification. | **Advisory Boundary & Dual 0.85 Threshold**: `choose` requires BOTH $\text{confidence} \ge 0.85$ and $\text{winner probability} \ge 0.85$; `check` requires $\ge 0.85$ (True) or $\le 0.15$ (False). Prompts must carry neutral observations only. |
| **3** | **SDK Retry Storms & Hanging Deadlocks** | Official SDK defaults to 2 retries, 500ms backoff, 30s timeouts; JS SDK had unhandled `AbortError`. Long timeouts stall multi-agent swarms. | **Hard 280ms Wall Deadline**: Single request, 0 retries. Covers DNS, TLS handshake, headers, and full body read. POSIX process group `SIGKILL` on timeout. Never hangs your agent. |
| **4** | **Sidecar Daemon Security Vulnerability** | *Winnow #1*: Running a local background HTTP daemon without auth or CORS allowed malicious web scripts to drain quotas or hijack context. | **Daemonless Pure CLI Architecture**: Zero open ports, zero listening daemons. Pure on-demand process execution via stdin/pipes, with zero persistent attack surface. |
| **5** | **Semantic Drift & Input Amputation** | *fast-jev #52*: Asking "Is this strictly non-reproducible?" coupled with aggressive pre-pruning erased necessary task constraints. | **Task-Continuity Metric & Full Visibility**: Prompts strictly ask *"What evidence/constraints are required to continue correctly?"* Input context is never amputated prior to judgment. |
| **6** | **Payload Corruption & Float Overflow** | *typesafe-mcp PR #15 / fast-jev #29*: JS float64 precision loss with integers $> 2^{53}$, truncated 16MB responses returning success, NaN acceptance. | **Strict Python Math & Boundary Validation**: Validates finite probabilities ($0.0 \le p \le 1.0$), rejects `NaN`, `inf`, booleans, and negative numbers. Hard 256 KiB input ceiling. |

---

## 🏛️ Architecture & Execution Flow

```
                               Incoming Payload
                      (CLI stdin / File / Agent Context)
                                      │
                                      ▼
               ┌──────────────────────────────────────────────┐
               │    Local Safety & Boundary Verifications     │
               │    • 256 KiB hard input ceiling              │
               │    • Secret & private key interceptor        │
               │    • O_NOFOLLOW / O_DIRECTORY path pinning   │
               │    • ~/Pictures directory lexical refusal    │
               └──────────────────────┬───────────────────────┘
                                      │
                                      ▼
               ┌──────────────────────────────────────────────┐
               │        Bounded Process Execution Engine      │
               │    • Subprocess POSIX process group          │
               │    • Monotonic deadline: 280 ms              │
               │    • Immediate SIGKILL upon expiration       │
               └──────────────────────┬───────────────────────┘
                                      │
             ┌────────────────────────┴────────────────────────┐
             │                                                 │
             ▼                                                 ▼
 [ OK / Decisive Verdict ]                         [ Timeout / 429 / Offline ]
 • choose: verified winning label                  • Exit Code 0 (Zero stderr)
 • check: boolean truth assessment                 • purify: 100% verbatim fallback
 • purify: verbatim LF line spans                  • choose/check: answer: null
 • Signed SHA-256 evidence receipt                 • Agent workflow proceeds safely!
```

---

## 🛠️ CLI Modes & Usage

### 1. `choose`: Closed-Set Decision Classification
Evaluate an ambiguous or qualitative scenario against 2–12 explicit, closed options.

```bash
printf '%s\n' 'Fix typo in documentation for install command' | \
  ask-jev choose \
    --question 'Which pull request category fits best?' \
    --option 'docs' \
    --option 'bugfix' \
    --option 'feature'
```

**JSON Output:**
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
    "probabilities": {
      "docs": 0.96,
      "bugfix": 0.03,
      "feature": 0.01
    }
  },
  "advisory": true,
  "receipt": "/path/to/evidence/receipt.json",
  "evidence_path": "/path/to/evidence/source.txt"
}
```

---

### 2. `check`: Evidence Support Verification
Determine whether the supplied evidence factually supports a specific claim.

```bash
git log -1 --stat | \
  ask-jev check \
    --question 'Does this commit include any database migration files?'
```

**JSON Output:**
```json
{
  "schema": "ask-jev.v1",
  "mode": "check",
  "status": "ok",
  "reason": "decisive",
  "answer": false,
  "judgment": 0.04,
  "advisory": true,
  "receipt": "/path/to/evidence/receipt.json",
  "evidence_path": "/path/to/evidence/source.txt"
}
```

---

### 3. `purify`: Verbatim Extractive Reading View
Extract only the relevant structural passages from verbose logs or source files while preserving byte-for-byte fidelity.

```bash
cat /var/log/build.log | \
  ask-jev purify \
    --query 'Compiler errors, stack traces, and failing assertions'
```

**JSON Output:**
```json
{
  "schema": "ask-jev.v1",
  "mode": "purify",
  "status": "ok",
  "reason": "verbatim_selection",
  "original_available": true,
  "spans": [
    {"start": 142, "end": 189}
  ],
  "text": "Traceback (most recent call last):\n  File \"app.py\", line 42, in <module>\n    connect()\nConnectionRefusedError: [Errno 61] Connection refused\n"
}
```

---

## 🤖 Agent Skill Integration

`ask-jev` includes a standard [Agent Skill specification](SKILL.md) compatible with modern coding agents.

### Example in Agent Workflows
When your agent encounters a large 150 KiB terminal log:
```bash
# Agent runs purify locally to inspect only substantive failure blocks
python3 ~/.agents/skills/ask-jev/scripts/ask_jev.py purify \
  --query 'Failure causes and error messages' \
  --input-file /tmp/test_output.log
```

If credentials are absent or the remote service is unreachable, `ask-jev` automatically emits the entire original input with zero crashes, allowing the agent to continue smoothly.

---

## 🔐 Environment Configuration

| Variable | Required | Description |
| :--- | :---: | :--- |
| `TYPESAFE_API_KEY` | Yes (for remote) | API key for the underlying SystemOne provider. |
| `HARNESS_JEV_ALLOW_REMOTE` | Yes (for remote) | Explicit consent gate (`1` or `true`). Prevents unintended network calls. |
| `JEV_MODEL` | No | Override provider model identifier. |
| `HARNESS_JEV_EVIDENCE_DIR` | No | Directory to persist raw evidence and execution receipts. |

---

## 🧪 Comprehensive Offline Test Suite

`ask-jev` comes with 146 offline unit tests covering edge cases, unicode normalization, path jail escapes, and process timeouts with 100% mocked isolation:

```bash
pytest -v
```

```
============================= 146 passed in 7.16s ==============================
```

---

<a name="chinese"></a>
# 中文深度技术文档

## 💡 诞生背景：大模型在自主智能体中的“微决策困境”

当自主编码智能体（Claude Code、Codex、Antigravity、OpenClaw 等）在执行重构、排错或多智能体协作时，执行循环中充斥着大量的**局部微决策**：
1. **任务路由分类**：这条用户指令应该派发给文档工具、测试套件还是重构 Agent？
2. **状态支持度验证**：命令执行输出或 Git Diff 是否真实佐证了“测试已通过”的断言？
3. **海量上下文提纯**：面对 200KB 的构建日志，如何抽取出真正的报错 Traceback，而不破坏物理行号、不引入任何臆造文本？

若对每一个微决策都调用 70B+ 重型大模型，将带来 **3~15 秒的严重延迟**、海量 Token 浪费以及提示词不稳定的风险；而若采用脆弱的纯正则规则，又缺乏语义理解能力。

`ask-jev` 正是为破解这一矛盾而生：**硬性限制 280ms 延迟上限、纯 Python 标准库零依赖、物理行级保真提纯、全链路 Fail-Open 弹性设计**。

---

## 🎯 社区实战踩坑复盘：全网研究暴露的问题与我们的对症解法

在前沿社区及开源项目（*NousResearch/Hermes, Winnow, fast-jev-compaction, typesafe-mcp, Pi, Prism, SemDecide*）对 JEV / SystemOne 的探索中，暴露了多项严重阻碍生产落地的隐患。

`ask-jev` 在架构设计之初便全面吸收了这些教训，做出了针对性的工程解法：

### 1. 杜绝“保留叙述却删掉执行证据”导致的幻觉完成（Anti-Narrative Illusion）
- **社区踩坑**：*fast-jev #65* 证实，在激进压缩上下文时，模型往往把底层工具的报错输出、退出码删掉，却保留了智能体的自然语言叙述。导致智能体看到“我已修复问题”的叙述，误以为已完成，连续 9 轮零工具调用发生幻觉。
- **ask-jev 解法**：在 `jev_context.py` 中引入 **语法与执行证据锚点保护（AST & Syntax Structural Pinning）**：
  - 自动识别并完整封闭 Python AST 模块、代码块（code fence）、Git Diff 文件变更。
  - 正则锁定 `Traceback`、`exit code`、`returncode`、`assert`、`panic`、`Error:` 等物理报错链。
  - 判定时**绝不拆散执行证据与叙述链条**，所有输出严格对应物理 LF 真实行。

### 2. 破除“让模型复述调用者自我结论”的虚假置信（Anti-Confirmation Bias）
- **社区踩坑**：*typesafe-mcp PR #13* 记录，智能体常在上下文中写下“明显是 P0 级别问题”，再向 JEV 提问确认，获得 0.99 的超高置信度。开发者误将其当成独立客观评判。
- **ask-jev 解法**：
  - 确立 **Advisory（咨询性）契约**：JEV 结果仅作辅助参考，不可直接用于越权授权、内存写入或安全放行。
  - **双 0.85 严格判定门槛**：`choose` 模式不仅要求整体置信度 $\ge 0.85$，还必须要求获胜选项概率 $\ge 0.85$；`check` 模式严格以 $\ge 0.85$ 判 True、$\le 0.15$ 判 False，其余模糊区间一律输出 `unknown`（`answer: null`），坚决不给伪确定性。

### 3. 终结 SDK 递归重试与尾延迟挂死（Anti-Retry Storms & Hard Timeout）
- **社区踩坑**：官方 Python SDK 默认 2 次重试、500ms 起步退避、30 秒总超时；OMP、SemDecide 也默认 10 秒超时。当网络抖动或服务排队时，高频调用的 Agent 会被完全拖死。
- **ask-jev 解法**：
  - **单次请求硬 280ms Wall Deadline**：DNS 解析、TLS 握手、HTTP 头与完整 Body 接收全包在 280ms 内，0 次重试。
  - **底层 POSIX 进程组强杀**：通过 `killpg(proc.pid, signal.SIGKILL)` 毫秒级回收子进程，绕过 Python 运行时线程阻塞。
  - **全链路 Fail-Open**：超时、网络中断或 401/402/429 报错时，进程**一律以 Exit Code 0 退出**，`purify` 原样输出全文，Agent 正常向下执行，不吐脏日志。

### 4. 坚守 Daemonless 架构，拒绝本地 Sidecar 攻击面（Zero Security Surface）
- **社区踩坑**：*Winnow #1* 为了省去进程启动开销，在本地后台启动了未鉴权的 HTTP Sidecar，缺乏 Origin/Content-Type 校验，恶意网页或本地进程可轻易探测并盗刷付费额度。
- **ask-jev 解法**：
  - **纯命令行管道执行（CLI-First）**：不启动任何后台 Daemon，不开任何本地监听端口，零常驻攻击面。
  - **文件描述符防越权钉死**：读取输入时逐级检查路径，使用 `O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK` 打开，彻底免疫符号链接穿透攻击。
  - **本地隐私防火墙**：词法与物理拦截 macOS `~/Pictures` 及其数据卷别名；内置正则嗅探，一旦发现私钥（`BEGIN PRIVATE KEY`）或 Bearer Token 立即阻断网络发送。

### 5. 矫正语义度量与提示词错位（Semantic Alignment）
- **社区踩坑**：*fast-jev #52* 问“材料是否绝对不可重新获取”，混淆了“任务必要性”与“可恢复性”，导致上下文被清空；Winnow 过于严苛的题面也误删了前置约束。
- **ask-jev 解法**：题面规范统一定义为 **“继续正确完成当前任务所需的证据、限制或更正是什么”**，候选文本随问题完整发送，禁止在模型判定前做有损裁切。

### 6. 严谨的数学验证与载荷边界（Strict Math & Payload Validation）
- **社区踩坑**：*typesafe-mcp PR #15* 与 *fast-jev #29* 暴露了 JS float64 精度损失、超大包隐式截断却报成功、非法 NaN 进入业务逻辑等缺陷。
- **ask-jev 解法**：严格限制输入 $\le 256\text{ KiB}$，响应 $\le 32\text{ KiB}$；强制校验浮点数为合法概率区间（$0.0 \le p \le 1.0$），遇到 `NaN`、`Inf`、负数或布尔混淆时严格抛出异常并降级。

---

## 🚀 核心工作模式与使用示例

### 1. `choose`：闭集决策分类
在 2~12 个明确的选项中做出语义归类，适合工单分类、路由分发、意图识别。

```bash
printf '%s\n' '修改 README 中安装命令的拼写错误' | \
  ask-jev choose \
    --question '这属于哪个 PR 类别？' \
    --option '文档修复' \
    --option '代码缺陷' \
    --option '新特性'
```

### 2. `check`：证据支持度断言
严格依据输入文本，判断某项断言是否得到事实支撑。

```bash
git log -1 --stat | \
  ask-jev check \
    --question '该提交是否包含数据库迁移文件？'
```

### 3. `purify`：原文保真结构提纯
从海量文本中只提取符合条件的真实物理代码块、Traceback 或 Diff 片段，**绝不重写、绝不摘要、绝无幻觉**。

```bash
cat /var/log/build.log | \
  ask-jev purify \
    --query '编译错误与失败断言'
```

---

## 📦 架构概览与文件清单

- `scripts/ask_jev.py`：主入口 CLI，内置同级脚本优先的双级级联路径解析。
- `scripts/jev_context.py`：认知投影引擎，负责 AST 切分、LF 物理行映射与证据链哈希收据。
- `scripts/harness_runtime.py`：POSIX 毫秒级受限执行器，负责子进程组强杀与超时隔离。
- `references/contract.md`：严格的输入输出规范与判定协议契约。
- `SKILL.md`：标准化 Agent 技能规范，无缝接入各类编程智能体。
- `tests/`：146 项离线单元测试，覆盖 Unicode 归一化、沙箱越权与极限超时。

---

## 📄 许可证声明 (License)

本项目采用 **GNU General Public License v3.0 or later (GPL-3.0-or-later)** 强 Copyleft 许可证。
详情请参阅 [LICENSE](LICENSE)。

Copyright (C) 2026 logicrw.
