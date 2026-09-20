---
name: ask-jev
description: Fast, bounded advisory judgments and verbatim evidence purification in coding-agent workflows. Use when: (1) routing subtasks or choosing among 2–12 explicit options (choose); (2) verifying whether build/test logs, diffs, or tool outputs strictly support a claim (check); (3) extracting verbatim error traces and failure contexts from dense terminal output (purify). Jev calls enforce a hard 280ms deadline and fail open. Exclude permission approval, irreversible actions, external fact lookup, exact arithmetic, and long-form text generation.
metadata:
  owner: logicrw
  version: "1.0.0"
---
# Ask Jev

## 1. Routing & Exclusions
- Invoke proactively when the next step needs a finite semantic choice, an evidence-support check, or an extractive reading view; the user need not name Jev or remember a command.
- Supply the task, original evidence and explicit options; use the specialized retrieval skill first when evidence is missing, and avoid duplicate judging when that skill already applied Jev.
- Use deterministic code for exact comparisons, arithmetic and permissions; do not call remotely when the user has forbidden remote processing.

## 2. Core Execution Skeleton
```bash
ASK_JEV="$HOME/.agents/skills/ask-jev/scripts/ask_jev.py"
# Classify among supplied options; text arrives on stdin or through --input-file.
printf '%s\n' 'A minimal documentation-only spelling correction.' | \
  python3 "$ASK_JEV" choose --question 'Which reading depth fits?' \
  --option brief --option detailed
# Check support in the provided evidence; this is not external fact verification.
printf '%s\n' 'The test process exited 7.' | \
  python3 "$ASK_JEV" check --question 'Does the evidence show a successful test run?'
# Select original passages while retaining the complete local source.
python3 "$ASK_JEV" purify --query 'Failure causes and corrections' --input-file evidence.txt
```

## 3. Guarantees & Invariants
- JSON stdout is the contract: inspect `status`; `unknown` and `fallback` mean continue the native workflow, never invent a choice or retry immediately.
- The shared runtime enables remote calls only with `TYPESAFE_API_KEY` and `HARNESS_JEV_ALLOW_REMOTE=1`; `JEV_MODEL` is optional, and the CLI never sets consent or loads credentials.
- Results are advisory, including high probabilities; keep original evidence authoritative and never use a verdict to grant permissions, execute an action, certify truth or promote memory.
- Provider, storage and deadline failures return exit 0 without stderr; purification falls back to the exact original text, while judgments return null.

## 4. References
- [CLI and output contract](references/contract.md)
- [Shared evidence, deadlines and retention](../agent-harness-governance/references/jev-skill-adapters.md)
- [Trigger cases](evals/trigger_cases.json)
- [Offline validation and trust boundary](reports/validation.json)
