<div align="center">

# ask-jev

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)
![Zero runtime dependencies](https://img.shields.io/badge/Runtime_dependencies-Zero-16a34a.svg)
![Advisory budget: 280ms](https://img.shields.io/badge/Advisory_budget-280ms-ea580c.svg)

**Bounded advisory decisions and verbatim reading views for AI agents.**

面向智能体的有界辅助决策与原文导读工具。

[English](#english) · [简体中文](#中文) · [Output contract](references/contract.md) · [Awesome Jev](https://logicrw.github.io/awesome-jev-projects/en/)

</div>

<a name="english"></a>
## English

`ask-jev` delegates small semantic judgments to TypeSafe's System One model through a Python standard-library CLI. It supports closed-set selection, evidence checks, ordered ratings, mixed questions over one state, and verbatim passage selection. The calling agent retains reasoning, verification and action authority.

### Choose the right primitive

- **`choose` / Choice:** one outcome from mutually exclusive alternatives, with the full distribution and confidence; not a multi-label classifier.
- **`check` / Noul:** the probability that one proposition is true given the supplied evidence; not the degree of severity, relevance or quality.
- **`score` / Score:** a rating across 2–10 ordered descriptions, with probabilities, confidence and the complete level legend.
- **`batch`:** 1–32 independent Choice, Noul or Score questions in one request; use several Nouls for labels that can all apply.
- **`purify`:** selected original physical-LF spans, with local source evidence; no generated summary.

This separation follows the official [Choice](https://docs.typesafe.ai/primitives/choice), [Noul](https://docs.typesafe.ai/primitives/noul) and [Score](https://docs.typesafe.ai/primitives/score) contracts. A Score is the probability-weighted mean of zero-based level positions, not a probability of truth; `judgment.normalized_score` divides it by `len(levels) - 1`. The distribution remains available because different distributions can have the same mean.

### Quick start

Python 3.10+ on a POSIX system is required; there are no third-party runtime dependencies. Configure `TYPESAFE_API_KEY` securely in the process environment and explicitly permit remote processing:

```bash
export HARNESS_JEV_ALLOW_REMOTE=1

printf '%s\n' 'Fix the installation guide spelling.' | \
  python3 scripts/ask_jev.py choose --question 'Which change category fits?' \
  --option docs --option bugfix --option feature

printf '%s\n' 'The test process exited 7.' | \
  python3 scripts/ask_jev.py check \
  --question 'Does the evidence show a successful test run?' --expect true

printf '%s\n' 'Export fails in Safari; Chrome works.' | \
  python3 scripts/ask_jev.py score --question 'How severe is this defect?' \
  --level 'Cosmetic defect; functionality works' \
  --level 'Functionality fails; a usable workaround exists' \
  --level 'Functionality fails; no usable workaround exists'

python3 scripts/ask_jev.py purify --query 'Failure causes and corrections' \
  --input-file test.log
```

Every command reads UTF-8 from stdin or `--input-file`. Without both environment gates, no remote call is made: judgments return `answer: null`, and purification returns the full original text inside JSON. Only the exact consent value `1` enables remote processing; `true` does not.

### One state, one request, several judgments

Use named JSON fields for observations and self-contained instructions for each question. Question IDs bind answers; they do not carry instructions to the model. References such as `ticket.text` are textual guidance to the model, not a local JSONPath evaluator. See the official [State](https://docs.typesafe.ai/concepts/state) and [speculative fan-out](https://docs.typesafe.ai/patterns/fan-out) guidance.

```bash
python3 scripts/ask_jev.py batch <<'JSON'
{
  "state": {
    "ticket": {"text": "Export crashes in Safari. Chrome works. Please refund my subscription."}
  },
  "questions": {
    "category": {
      "type": "choice",
      "instructions": "Which team should first handle `ticket.text`?",
      "criteria": {
        "engineering": "A broken product feature needs investigation",
        "billing": "The message concerns only charges or refunds",
        "other": "Neither description applies"
      }
    },
    "severity": {
      "type": "score",
      "instructions": "How severe is the defect described in `ticket.text`?",
      "criteria": [
        "Cosmetic defect; functionality works",
        "Functionality fails; a usable workaround exists",
        "Functionality fails; no usable workaround exists"
      ]
    },
    "refund_requested": {
      "type": "noul",
      "instructions": "Does `ticket.text` explicitly request a refund?"
    },
    "workaround_present": {
      "type": "noul",
      "instructions": "Does `ticket.text` identify a usable workaround?",
      "expect": true
    }
  }
}
JSON
```

All questions see the same state and are independent: one cannot read another's answer. The caller selects the applicable branch after the response, for example inspecting severity only when the category is engineering. An unused speculative answer's uncertainty does not block the whole batch. `expect` is local policy, removed before the provider request to avoid suggesting the desired answer.

### Verify, then escalate when needed

JSON stdout keeps `schema: ask-jev.v1`; the new modes and fields are additive. Existing `choose`, `check` and `purify` behavior remains available.

- `choose` returns an answer only when both confidence and winner probability are at least 0.85.
- `check` returns true at or above 0.85, false at or below 0.15, and `unknown` otherwise.
- `score` returns the raw ordinal score only when confidence is at least 0.85; otherwise `answer` is null while the complete `judgment` remains available.
- `escalation` reports `required`, `target` and `reason`: uncertainty, unavailability, or a decisive Noul contradicting explicit `expect`. A false answer alone is not an escalation trigger.

For example, an uncertain result carries:

```json
{"required": true, "target": "primary_model", "reason": "uncertain"}
```

This is a request for the caller to resume reasoning or the native workflow. It does not call a larger model, involve a human, retry, or grant permission. For `batch`, escalation belongs to each entry in `decisions`; top-level `status: "ok"` means the response validated, not that every judgment was decisive or every claim was true. Full details are in the [output contract](references/contract.md).

These thresholds are local operating policy, not locally calibrated accuracy guarantees. Official [confidence guidance](https://docs.typesafe.ai/confidence) recommends validating thresholds against the domain and consequences. The CLI retains provider confidence rather than presenting an invented entropy threshold as an official rule.

### Failure and evidence boundaries

The advisory operation shares a 280ms budget across evidence preparation, one HTTP request and receipt persistence, with up to 5ms process-reap wait. This excludes CLI startup and native input reading; operating-system scheduling prevents a hard real-time end-to-end guarantee. There are no retries, daemons or listening ports.

Missing consent/key, 401/402/429, connection failure, malformed responses, storage failures and deadline expiry silently return `fallback` with exit 0. Invalid local input returns structured `error` with exit 64; argparse usage errors use exit 2. Exit 0 alone does not prove that Jev ran.

Raw purification text or structured judgment evidence is saved privately before evaluation; successful results expose exact `receipt` and `evidence_path` pointers. Source hashes establish identity, not truth. Structural grouping protects recognized code, diffs and tracebacks, but semantic passage selection can still omit relevant context: consult the retained source when that matters. Sensitive-text heuristics are an additional guard, not proof that arbitrary content is safe to transmit.

Limits are 256 KiB input, 96 KiB encoded request, 28 KiB state/question pair and 32 KiB response. Batch questions share these limits and one deadline; the implementation does not split an oversized batch into additional network requests.

### Configuration and skill use

| Variable | Meaning |
| --- | --- |
| `TYPESAFE_API_KEY` | Required for remote calls; never loaded from credential files by this CLI. |
| `HARNESS_JEV_ALLOW_REMOTE` | Required exact value `1` for remote processing. |
| `JEV_MODEL` | Optional provider model override. |
| `HARNESS_JEV_EVIDENCE_DIR` | Optional private evidence directory; ownership and no-symlink checks apply. |

The entrypoint loads the colocated `scripts/jev_context.py` first, with the canonical `~/.agents/scripts` runtime as a fallback. Keep the CLI and its runtime together when installing this repository as a skill. [SKILL.md](SKILL.md) supplies concise agent instructions; an existing shared skill installation should be updated through its normal governance workflow.

```bash
python3 ~/.agents/skills/ask-jev/scripts/ask_jev.py batch --input-file questions.json
python3 -m pytest tests/
```

Tests use local fixtures and mocked provider results; passing them establishes interface, evidence and failure behavior, not live-service latency or semantic accuracy.

<a name="中文"></a>
## 中文

`ask-jev` 是智能体的辅助判断工具：让 Jev 在既有证据上做小而明确的判断，主模型继续负责推理、复核与行动。运行代码仅依赖 Python 标准库，保留原有 `choose`、`check`、`purify`，新增 `score` 与 `batch`；JSON 契约仍为 `ask-jev.v1`。

### 原语应当各司其职

- **闭集选一项用 Choice**：分类候选互斥，保留全部概率和置信度。
- **多个标签可同时成立用多个 Noul**：每个命题独立判断，不能把互斥分类硬当作多标签。
- **严重程度等有序分级用 Score**：提供 2–10 个完整、具体、从低到高的描述，返回等级序号的概率加权均值、全部分布和图例；归一化值是尺度位置，不是“事实为真的概率”。
- **多项独立判断用 batch**：同一结构化 State 只发一个请求，题目数量为 1–32；调用方根据适用分支消费结果，不能把每个未用分支的未知状态都当作整体阻断。
- **重点导读用 purify**：选取原文物理 LF 行区间，保留本地完整证据，不生成改写摘要。

上方示例可直接运行。题目 ID 只用于匹配响应，完整问题和字段路径必须写入 `instructions`；路径是给模型的语义提示，不会在本地执行 JSONPath。Score 的每级描述独立评估，应写明情形，不使用“比上一级更严重”之类依赖邻居的描述。

### 升级信号与降级契约

`escalation` 显式告诉调用方是否需要接手，以及原因是 `uncertain`、`unavailable` 还是 `expectation_mismatch`。`check --expect true|false` 和 batch 中 Noul 的 `expect` 只参与本地比较，不发给模型；明确判断为 false 本身不代表故障。升级目标为 `primary_model`，工具不会自动调用其他模型、联系人工或授予权限。

`choose` 保留“置信度和获胜概率均至少 0.85”的门槛，`check` 保留 0.85/0.15 双阈值，`score` 在置信度至少 0.85 时给出数值答案。低置信度返回 `unknown`，保留判断原始分布以供复核。阈值属于本地保守策略，尚不能当作准确率承诺。

只有 `TYPESAFE_API_KEY` 和 `HARNESS_JEV_ALLOW_REMOTE=1` 同时存在才联网，`true` 不等于 `1`。欠费、鉴权、限流、断网、超时或存储异常均静默返回原生降级结果：判断为空，提纯返回全文；输入或命令错误仍明确报错。

280ms 是证据处理、一次 HTTP 请求与凭证保存共用的预算，另有最多 5ms 进程回收等待；不含 CLI 启动和原生输入读取，也不构成操作系统级硬实时保证。没有重试或常驻服务。证据路径、输入预算与具体输出字段见 [契约说明](references/contract.md)，测试命令为 `python3 -m pytest tests/`；离线测试通过不代表真实服务质量或线上语义效果已验证。

## Sources and license

Design references: [official skill](https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md), [documentation index](https://docs.typesafe.ai/llms.txt), [API](https://docs.typesafe.ai/api), and the primitive pages linked above. Local limits, deadlines, abstention thresholds and permission boundaries belong to this project, not the provider specification.

[GNU GPL-3.0-or-later](LICENSE). Copyright (C) 2026 logicrw.
