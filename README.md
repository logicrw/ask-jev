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
  <strong>Ultra-fast, fail-open advisory decisions and verbatim extractive reading view for AI coding agents and CLI pipelines.</strong>
</p>

---

## ⚡ Why ask-jev?

When autonomous coding agents (Claude Code, Codex, Antigravity, OpenClaw, Maestro) or automated CI pipelines need to make small semantic decisions, they face a painful dilemma:

1. **Frontier LLMs are slow and heavy**: Waiting 3 to 15 seconds for a 70B+ model just to classify a route or verify a test status wastes budget and stalls the execution loop.
2. **Hallucination & Paraphrasing Corruption**: Generative summaries often drop critical line numbers, alter error signatures, strip indentation, or invent details.
3. **Fragile Error Handling**: Most agent tools crash or abort when a downstream API times out, has a quota hiccup, or encounters an unexpected format.

`ask-jev` solves this with a **deterministic, fail-open advisory cognitive layer**:

```
                       ┌────────────────────────────────────────────────────────┐
                       │                   Incoming Payload                     │
                       │           (CLI stdin / File / Agent Context)           │
                       └──────────────────────────┬─────────────────────────────┘
                                                  │
                                                  ▼
                          ┌───────────────────────────────────────────┐
                          │   Local Safety & Invariant Verification   │
                          │   • 256 KiB hard input ceiling            │
                          │   • Secret / Private Key interceptor      │
                          │   • O_NOFOLLOW symlink path pinning       │
                          │   • ~/Pictures traversal refusal          │
                          └───────────────────────┬───────────────────┘
                                                  │
                                                  ▼
                          ┌───────────────────────────────────────────┐
                          │       Bounded Execution Engine (<280ms)   │
                          │   • Subprocess POSIX process group        │
                          │   • DNS + TLS + Body in single deadline   │
                          │   • Hard SIGKILL on expiration            │
                          └───────────────────────┬───────────────────┘
                                                  │
                       ┌──────────────────────────┴──────────────────────────┐
                       │                                                     │
                       ▼                                                     ▼
           [ OK / Decisive Verdict ]                             [ Timeout / 429 / Network Failure ]
           • `choose`: high-confidence label                     • Exit code 0 (Zero stderr)
           • `check`: boolean support verdict                    • `purify`: 100% verbatim fallback
           • `purify`: verbatim LF line spans                    • `choose/check`: answer: null
           • Signed evidence hash & receipt                      • Native agent workflow continues!
```

---

## 🌟 Core Superpowers

### 1. Hard 280ms Latency Budget
Total roundtrip time (DNS resolution, TLS handshake, headers, response body, and receipt storage) is strictly capped at **280 ms**. If the provider or connection stalls, the process group is reaped immediately. Your agent **never hangs**.

### 2. Zero-Hallucination Verbatim Purification (`purify`)
Unlike generative compressors that rewrite text, `purify` selects **verbatim physical LF lines** from original AST-coherent structures:
- Preserves full Python AST modules, functions, classes, decorators.
- Preserves whole git diff hunks and file mode transitions.
- Preserves fenced markdown blocks and runtime tracebacks.
- Drops irrelevant noise without altering a single byte of source evidence.

### 3. Fail-Open Architecture
Every transient failure (401/402/429 HTTP status, network loss, DNS failure, timeout) exits cleanly with `code 0`:
- **`purify`** falls back to returning the full original text.
- **`choose` / `check`** returns `status: fallback` with `answer: null`.
- Pipelines and agents continue seamlessly without error handling boilerplate.

### 4. Zero External Dependencies
Written entirely with the **Python standard library** (`urllib`, `selectors`, `signal`, `ast`, `os`, `json`). Zero `pip install` bloat. Ready to run on any POSIX system with Python 3.10+.

### 5. Defensive Security & Privacy Invariants
- **Secret Interception**: Regular expressions inspect payloads for private keys (`-----BEGIN PRIVATE KEY-----`), bearer tokens, and API credentials before anything touches the wire. If detected, remote transmission is automatically blocked.
- **Path Sanitization**: Resolves paths component-by-component using `O_DIRECTORY | O_NOFOLLOW` to prevent symlink traversal attacks.
- **Strict Privacy**: Lexically and physically refuses access to user privacy zones (e.g. `~/Pictures` and its macOS Data Volume aliases).

---

## 🚀 Installation

### Option A: Direct Clone (Recommended for Agents)
```bash
git clone https://github.com/logicrw/ask-jev.git ~/.agents/skills/ask-jev
chmod +x ~/.agents/skills/ask-jev/scripts/ask_jev.py
```

### Option B: Local Editable Pip Install
```bash
git clone https://github.com/logicrw/ask-jev.git
cd ask-jev
pip install -e .
```

---

## 🛠️ CLI Usage & Modes

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

**Output:**
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
> **Contract Guarantee**: `answer` is committed only when confidence $\ge 0.85$ and the winning option probability $\ge 0.85$. Otherwise, `answer` is `null` with `status: unknown`.

---

### 2. `check`: Evidence Support Verification
Determine whether the supplied evidence factually supports a specific assertion.

```bash
git log -1 --stat | \
  ask-jev check \
    --question 'Does this commit include any database migration files?'
```

**Output:**
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
> **Contract Guarantee**: Returns `true` for probability $\ge 0.85$, `false` for $\le 0.15$, and `null` for intermediate ambiguities ($0.15 < p < 0.85$).

---

### 3. `purify`: Verbatim Extractive Reading View
Extract only the relevant structural passages from verbose logs or source files while preserving byte-for-byte fidelity.

```bash
cat /var/log/build.log | \
  ask-jev purify \
    --query 'Compiler errors, stack traces, and failing assertions'
```

**Output:**
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

## 🤖 AI Agent Integration

`ask-jev` includes a standard [Agent Skill specification](SKILL.md) compatible with modern coding agents.

### Skill Trigger Example
When your agent encounters a large 150KB terminal log:
```bash
# Agent runs purify locally to inspect only substantive failure blocks
python3 ~/.agents/skills/ask-jev/scripts/ask_jev.py purify \
  --query 'Failure causes and error messages' \
  --input-file /tmp/test_output.log
```

If the API key is absent or the remote service is unreachable, `ask-jev` automatically emits the entire original input with zero crashes, allowing the agent to continue smoothly.

---

## 🔐 Environment Configuration

| Variable | Required | Description |
| :--- | :---: | :--- |
| `TYPESAFE_API_KEY` | Yes (for remote) | API key for the underlying SystemOne provider. |
| `HARNESS_JEV_ALLOW_REMOTE` | Yes (for remote) | Explicit consent gate (`1` or `true`). Prevents unintended network calls. |
| `JEV_MODEL` | No | Override provider model identifier (defaults to standard fast model). |
| `HARNESS_JEV_EVIDENCE_DIR` | No | Directory to persist raw evidence and execution receipts. |

*Note: In offline environments or without credentials, `ask-jev` acts as a fail-open passthrough tool.*

---

## 🧪 Comprehensive Offline Test Suite

`ask-jev` comes with an extensive offline test suite covering edge cases, unicode normalization, path jail escapes, and process timeouts with 100% mocked isolation:

```bash
pytest -v
```

```
============================= 146 passed in 7.16s ==============================
```

---

## 📄 License & Governance

Licensed under the **GNU General Public License v3.0 or later (GPL-3.0-or-later)**.
See [LICENSE](LICENSE) for details.

Copyright (C) 2026 logicrw.
