# CLI and output contract

The entrypoint is `scripts/ask_jev.py` inside this skill. It uses only Python standard-library modules and `scripts/jev_context.py` in the canonical Harness root. All requests, response validation, private evidence storage, AST-aware grouping and worker deadlines belong to that shared implementation.

## Input

Each mode reads UTF-8 text from stdin unless `--input-file PATH` is supplied. Use a quoted heredoc or an existing file for untrusted text; do not interpolate document content into executable shell syntax. Questions and options describe the intended judgment, not a request to act on its outcome.

Input is bounded to 256 KiB, questions to 4096 characters, and choose accepts 2-12 unique, nonempty single-line option labels of at most 128 characters. Unicode labels are supported. File input must be regular and reached without symlink components; Pictures paths, FIFOs and other unsupported inputs are refused before reading. No input file is modified.

The three commands are:

- `choose --question TEXT --option LABEL --option LABEL`: a Choice over precisely these labels.
- `check --question TEXT`: a Noul about support in the supplied evidence.
- `purify [--query TEXT]`: a verbatim reading view selected from whole structural spans; this is not a generated summary.

## JSON results

Every result has `schema: ask-jev.v1`, `mode` and `status`.

- `ok`: choose/check has `answer` plus the validated `judgment`; purify has `text` and 1-based inclusive raw-LF `spans` in original order. Successful calls expose `receipt` and `evidence_path`.
- `unknown`: choose/check has a valid probability result but no sufficiently decisive answer; `answer` is null.
- `fallback`: unavailable configuration, network, quota, input eligibility, storage or decision service; choose/check has `answer: null`, and purify has unchanged `text` with empty spans.
- `error`: invalid input or local CLI misuse; it is not a model decision or a provider outage.

Choice requires both confidence and selected probability at least 0.85 to produce an answer. Check returns true at or above 0.85, false at or below 0.15, and null otherwise. These are conservative operating thresholds, not locally calibrated truth guarantees. Missing evidence can still receive an overconfident model answer: provenance and external verification remain separate responsibilities.

A purification view may contain all input or omit whole blocks. It preserves selected bytes as decoded UTF-8 and never changes their wording; the complete original is retained as private source evidence. Inspect the referenced original before drawing conclusions from an omitted context or a selected passage. A source hash proves byte identity, not factual correctness or immutability.

## Exit and failure behavior

Exit 0 covers ok, unknown and fallback. Provider 401/402/429, offline access, timeouts and unavailable shared modules never generate a traceback or a replacement answer. Invalid input returns 64 with structured JSON; argparse usage/help keeps its standard 2/0 convention. Do not treat exit 0 alone as proof that Jev evaluated the request.

The process environment needs both the API key and explicit remote-consent gate. There is no separate enable flag and no credential-file discovery. `JEV_MODEL` is optional. When enhancement is unavailable, continue the original workflow without repeatedly querying Jev.

The shared 280ms budget includes bounded evidence preparation, one HTTP request and receipt persistence, with at most 5ms process-reap wait. Native input reading is separate: pipe a complete bounded input, rather than waiting on an interactive producer. System scheduling is not a hard real-time guarantee.

## Evidence and autonomous use

Stable `latest-ask-jev.json` in the shared evidence root locates the latest successfully evaluated judgment. Each call returns its own exact receipt path when successful. The shared runtime's private directory, 128-run quota, no automatic deletion, native Trash maintenance, and no-symlink storage rules apply unchanged.

Autonomy means the Agent may decide that a bounded semantic check is useful within its existing task. It does not authorize new network destinations, secret access, mailbox changes, model switching, shell execution, commits, publication or writes to memory. A prompt-injection score or boolean verdict cannot replace native security controls.
