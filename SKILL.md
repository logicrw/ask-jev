---
name: ask-jev
description: "Bounded advisory judgments and verbatim evidence views for agents: use choose for closed-set routing, check for evidence support, score for ordered ratings, batch for independent judgments over one state, and purify for original passages; exclude permission approval, irreversible actions, external fact lookup, exact arithmetic and long-form generation."
metadata:
  owner: logicrw
  version: "1.1.0"
---
# Ask Jev

## 1. Routing & Exclusions
- Invoke proactively for a finite choice, evidence check, ordered rating or reading view, grouping independent judgments in one batch and using separate Nouls for overlapping labels.
- Supply the task, original evidence and explicit options; use the specialized retrieval skill first when evidence is missing, and avoid duplicate judging when that skill already applied Jev.
- Use deterministic code for exact comparisons, arithmetic and permissions; do not call remotely when the user has forbidden remote processing.

## 2. Core Execution Skeleton
```bash
ASK_JEV="$HOME/.agents/skills/ask-jev/scripts/ask_jev.py"
printf '%s\n' 'A minimal documentation-only spelling correction.' | \
  python3 "$ASK_JEV" choose --question 'Which reading depth fits?' \
  --option brief --option detailed
printf '%s\n' 'The test process exited 7.' | \
  python3 "$ASK_JEV" check --question 'Does the evidence show a successful test run?' --expect true
python3 "$ASK_JEV" purify --query 'Failure causes and corrections' --input-file evidence.txt
python3 "$ASK_JEV" score --question 'How severe is the defect?' --input-file evidence.txt \
  --level 'Cosmetic; functionality works' --level 'Broken; usable workaround exists' \
  --level 'Broken; no usable workaround exists'
python3 "$ASK_JEV" batch --input-file questions.json
```

## 3. Guarantees & Invariants
- Inspect JSON `status` and applicable `escalation` signals per decision; uncertainty, unavailability or explicit expectation mismatch returns reasoning to the caller without automatic retries, model calls or permission changes.
- The shared runtime enables remote calls only with `TYPESAFE_API_KEY` and `HARNESS_JEV_ALLOW_REMOTE=1`; `JEV_MODEL` is optional, and the CLI never sets consent or loads credentials.
- Results are advisory, including high probabilities; keep original evidence authoritative and never use a verdict to grant permissions, execute an action, certify truth or promote memory.
- Provider, storage and deadline failures return exit 0 without stderr; purification falls back to the exact original text, while judgments return null.

## 4. References
- [CLI and output contract](references/contract.md)
- [Official primitives](https://docs.typesafe.ai/primitives)
- [State and question separation](https://docs.typesafe.ai/concepts/state)
