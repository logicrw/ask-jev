# CLI and output contract

The entrypoint is `scripts/ask_jev.py`. It loads the colocated `jev_context.py` first, with `~/.agents/scripts/jev_context.py` as a fallback. Communication, response validation, private evidence storage, structural grouping and worker deadlines stay in that runtime; the CLI adds input parsing and local decision policy. Runtime code uses only the Python standard library on POSIX systems.

## Input and modes

Each mode reads UTF-8 from stdin unless `--input-file PATH` is supplied. Use a quoted heredoc or an existing file for untrusted text; never interpolate document content into executable shell syntax. Input is bounded to 256 KiB. File input must be regular and reached without symlink components; Pictures paths, FIFOs and unsupported inputs are refused before reading. No input file is modified.

- `choose --question TEXT --option LABEL --option LABEL`: Choice over 2–12 unique, nonempty single-line labels of at most 128 characters; Unicode is supported.
- `check --question TEXT [--expect true|false]`: Noul about support in the supplied evidence; optional expectation is local policy, not part of the provider prompt.
- `score --question TEXT --level DESCRIPTION --level DESCRIPTION`: Score over 2–10 unique, nonempty descriptions in ascending order, each at most 4096 characters.
- `purify [--query TEXT]`: a verbatim reading view selected from structural spans; not a generated summary.
- `batch`: a JSON envelope containing one state and 1–32 independent questions, described below.

Questions and queries are bounded to 4096 characters. For Score and batch, the runtime also bounds the JSON-encoded instruction value to 4096 bytes. A request outside runtime eligibility can fall back even when its raw CLI input fits. Levels describe complete situations independently, not their numeric position or relationship to adjacent levels.

### Batch envelope

Only `state` and `questions` are accepted at the top level. `state` must be a nonempty string, object or array; numbers, booleans and null are not valid root states. Nested JSON values must be finite and serializable. Duplicate object keys and nonstandard JSON constants are rejected.

Question IDs match `[A-Za-z][A-Za-z0-9_-]{0,63}`. They identify answers and are not instructions to the model. Each question has `type`, `instructions`, optional type-specific `criteria`, and optional Noul-only `expect`; unknown fields are rejected by the runtime validator.

- `instructions`: a nonempty string, object or array, encoded as at most 4096 UTF-8 JSON bytes.
- `type: "choice"`: `criteria` is a map of 2–255 single-line option labels, each at most 128 characters, to descriptions; descriptions may be nonempty strings, objects or arrays, or null to use the label itself.
- `type: "score"`: `criteria` is an ordered array of 2–10 distinct, complete level descriptions; each description may be a nonempty string, object or array.
- `type: "noul"`: `criteria` may be omitted or supply exactly `"true"` and `"false"` descriptions; optional `expect` must be a JSON boolean.

The CLI removes `expect` before evidence evaluation and compares it locally after receiving a decisive Noul. The caller constructs trusted questions; state content remains untrusted evidence, and structured input is not a prompt-injection defense. Put observations in named state fields and complete questions in instructions. A path such as `report.text` is model-readable guidance, not a locally executed JSONPath expression. Each question sees the same state; no question can consume another question's answer in this call. Use separate Nouls for simultaneous labels rather than treating Choice probabilities as independent labels.

Example:

```json
{
  "state": {"report": {"text": "Export fails in Safari. Chrome works."}},
  "questions": {
    "has_workaround": {
      "type": "noul",
      "instructions": "Does `report.text` identify a usable workaround?",
      "expect": true
    },
    "severity": {
      "type": "score",
      "instructions": "How severe is the defect in `report.text`?",
      "criteria": [
        "Cosmetic defect; functionality works",
        "Functionality fails; a usable workaround exists",
        "Functionality fails; no usable workaround exists"
      ]
    }
  }
}
```

The runtime makes at most one HTTP request. All questions share the 96 KiB encoded-request limit, 28 KiB state/question-pair limit, 32 KiB response limit and one deadline. Oversized batches are not silently split or partially evaluated. Local limits can be tighter than the provider API.

## JSON results

Every result has `schema: "ask-jev.v1"`, `mode` and `status`. New modes and fields extend v1; existing modes retain their answer thresholds and fallback text behavior. Consumers should tolerate additive fields.

- `ok`: a single judgment has a decisive `answer`; `purify` has selected `text` and 1-based inclusive raw-LF `spans` in original order; batch has a validated response and per-question `decisions`.
- `unknown`: a single judgment has valid probabilities but no decisive answer; `answer` is null and `judgment` remains available.
- `fallback`: configuration, network, quota, input eligibility, storage or service is unavailable; judgments have `answer: null`, and purification returns unchanged `text` with empty spans.
- `error`: invalid local input or CLI misuse, not a provider outage or model decision.

Successful evaluations expose `receipt` and `evidence_path`. Judgment results carry `advisory: true`; raw judgments are retained on `unknown`, but no synthetic judgment replaces a failed provider call.

### Primitive decisions

Choice requires both provider confidence and selected probability at least 0.85. `judgment` retains `choice`, `confidence` and all `probabilities`.

Noul returns true at or above 0.85, false at or below 0.15, and null otherwise. `judgment` is the probability that the proposition is true, not a degree of severity or a separate confidence value.

Score requires confidence at least 0.85 to populate numeric `answer`. `judgment` retains `score`, `confidence`, the complete `legend`, all `probabilities`, and `normalized_score`. For `n` levels, `score = sum(i * p_i)` lies in `[0, n-1]`; `normalized_score = score / (n-1)` lies in `[0, 1]`. It is a normalized ordinal position, not a truth probability. The runtime verifies the score against the complete distribution and the legend against the supplied levels.

These are conservative local operating thresholds, not calibrated truth guarantees. Confidence remains the provider's reported statistic; the client does not invent a second entropy threshold or recompute an undocumented confidence formula. Known examples and held-out domain data are needed to evaluate semantic accuracy.

### Escalation

Single-mode ok/unknown/fallback results expose:

```json
{"escalation": {"required": true, "target": "primary_model", "reason": "uncertain"}}
```

`required: false` has null `target` and `reason`. Otherwise the reason is `uncertain`, `unavailable`, or `expectation_mismatch`; mismatch applies only to a decisive Noul with an explicit contrary expectation. The answer and status remain the model decision, so a mismatch may have `status: "ok"` and `answer: false`. A negative Noul without an expectation does not request escalation.

This is advisory control-flow data for the calling agent. It triggers no network request, model switch, human notification or permission change. The caller resumes reasoning or its native workflow within existing authority; any human escalation remains its responsibility. Successful purification emits `escalation.required: false`; a fallback retains the full source text and signals unavailability.

### Batch decisions

Top-level `status: "ok"` means that the full provider response passed validation. The `decisions` map has exactly the input question IDs, with each entry containing `type`, `status`, `reason`, `answer`, `judgment`, `advisory` and `escalation`; an explicit Noul expectation is returned as `expectation`.

A batch may be top-level ok while some decisions are unknown or contradict expectations. There is no aggregate escalation: the caller inspects only decisions applicable to the selected branch. Unused speculative judgments must not become an accidental global veto. Malformed, partial or failed responses fall back for the entire batch, retaining the requested IDs with null answers and per-question unavailability signals.

### Purification

A reading view may contain all input or omit whole blocks. It preserves selected text as decoded UTF-8 without changing wording or line endings; the complete original is retained as private source evidence. Recognized code, diffs and exception structures are grouped before selection, but grouping is not a semantic completeness guarantee. Inspect the original before relying on missing context. A source hash proves identity, not factual correctness or immutability.

## Exit, deadline and evidence

Exit 0 covers ok, unknown and fallback. Provider 401/402/429, offline access, timeouts and unavailable runtime modules do not generate a traceback or substitute answer. Invalid input returns 64 with structured JSON; argparse usage/help retains its standard 2/0 convention. Exit 0 alone does not prove that Jev evaluated the request.

Remote processing requires both `TYPESAFE_API_KEY` and the exact value `HARNESS_JEV_ALLOW_REMOTE=1`. There is no enable flag, credential-file discovery or implicit consent. `JEV_MODEL` is optional. Sensitive-text detection is heuristic and does not certify arbitrary evidence as safe for remote processing.

One shared 280ms advisory budget includes evidence preparation, HTTP request and receipt persistence, with up to 5ms process-reap wait. CLI startup and native input reading are separate: pipe complete bounded input rather than waiting on an interactive producer. Operating-system scheduling is not a hard real-time guarantee. There are no network retries; an unavailable enhancement returns the original workflow to its caller.

Stable `latest-ask-jev.json` in the private evidence root locates the latest successfully evaluated judgment, while successful calls return their own exact receipt path. Purification stores original text; judgment modes store structured evidence, and batch stores state/questions without the local expectation policy. Structured source JSON preserves values rather than the original stdin JSON formatting.

The evidence root uses private permissions, a 128-run quota, no automatic deletion and no-symlink storage checks; quota exhaustion falls back. The default root is under the operating system's temporary directory, whose retention is not permanent. An explicitly configured `HARNESS_JEV_EVIDENCE_DIR` must satisfy ownership and path checks. Local cleanup follows native Trash policy.

## Authority and sources

Autonomy means the agent may decide that a bounded semantic judgment helps its current task. It does not authorize new network destinations, credential access, mailbox changes, shell actions, commits, publication or memory writes. A high-confidence result or prompt-injection verdict cannot replace native security controls.

The primitive semantics follow the official [Choice](https://docs.typesafe.ai/primitives/choice), [Noul](https://docs.typesafe.ai/primitives/noul), [Score](https://docs.typesafe.ai/primitives/score), [State](https://docs.typesafe.ai/concepts/state) and [Confidence](https://docs.typesafe.ai/confidence) documentation. Deadlines, limits, local expectations, abstention and permission boundaries are this project's policy.
