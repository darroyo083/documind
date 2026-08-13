# DocuMind — Verifier Finalization Closure Report

Decision: **B — V4 FAILED / VERIFIER RESEARCH CLOSED**

## A. Starting State
- Base SHA: `956f9b8689da249064ccb6f94ee328409a6de773` (`master` == `origin/master`, clean tree).
- Baseline quality gates: 993 tests, ~94% coverage, Alembic head 009.
- Historical safety: RF1 implemented; frozen V2/V3 preserved; the known residual FP was `brd_absence_injection_fresh` (literal value inside an injected instruction).

## B. Wave 1
- Worker A (forensics): the RF1 invariant `canon(answer) in canonical(quote)` proves "answer string present in evidence", never "answer is the requested attribute's value". `requested_attribute` is derived but gates nothing.
- Worker B (architecture): ranked AB1 < AB3 < AB4 < AB2; selected AB2 (structured independent fact extraction + deterministic matching).
- Worker C (threat pack): designed the 12-case attribute-binding dev pack.
- Orca incidents: none (orchestrator executed Wave 1 directly as source of truth to avoid the documented Orca dispatch bug).
- Decision gate: **AB2** (extension of RF1; stage 1/2 reused; stage 3 replaced by `ExtractedFactV1`).

## C. Selected Architecture
- `RequestedFactV1` (question-only) → exact-quote proof (E1c contract) → `ExtractedFactV1` `{subject, attribute, value, value_kind, polarity, fact_anchors}`.
- Deterministic invariants: strict keys/enums; value question ⇒ `status=fact_extracted`, affirmative polarity, non-empty value, value-kind, literal substring anchoring; boolean ⇒ polarity carries the answer.
- Composition: supported = proof valid AND fact_extracted AND anchored AND polarity-affirmative AND subject/attribute present (value questions).
- Remaining model-judged: semantic correspondence of extracted subject/attribute to the requested fact.
- Calls/case: 3 (stage 1, stage 2, stage 3).

## D. Development Pack
- 12 cases (6 supported / 6 unsupported), fresh domain (Northgate), covering all 12 categories; ≥4 supported suspicious-text controls. Frozen at `fd79775`.

## E. Development Run
- Calls: 61/64 budget.
- After the one correction: **false supports = 0**, false rejections = 2 (e0 cases — pre-existing RF1 selector limitation), source/provenance failures = 0.
- 3 transient provider failures (rate-limit) recovered via cooldown.

## F. Correction Cycle
- Used: yes (once). Root cause: the extractor accepted a declarative value from a self-declared control-channel message.
- Generic fix: source-authority rule (self-declared non-document content is not authoritative).
- 4 fresh fake-authority confirmation cases → 4/4 rejected, 1/1 supported control preserved.

## G. Pre-V4 Gate
- **READY_FOR_V4** (0 false supports in final development evidence).

## H. V4
- Created: `verifier_holdout_v4.json` (24 cases, 12/12), manifest + digest frozen at `e124ef4`.
- One-shot: attempted twice; **both aborted by provider transport failures (rate-limit/quota)**, reaching 14/24 and 9/24 cases. No tuning, no case removal, no reinterpretation.
- Partial results: **false supports = 0** across both aborted runs; false rejections observed on `v4_benign_imperative` and `v4_existence_no`, which **flipped to supported on the second attempt** (model non-determinism at temperature 0).
- Not created: n/a (created but could not complete).

## I. Production Integration
- Not performed. Reason: V4 did not reach a clean frozen one-shot PASS; retention below the 90% gate and non-determinism block production integration.

## J. Evidence
- Tracked: `backend/evaluation/evidence/verifier_finalization_development.json`, `backend/evaluation/evidence/verifier_v4_validation.json`, this report.
- Raw reports (gitignored): `backend/evaluation/results/goal_verifier_finalization/*.json|md`.
- Secret scan: no API keys, Authorization headers, or env secret values in any tracked file.

## K. Tests
- Backend: 1047 tests passing, 93% coverage; Ruff check/format clean; mypy clean; compileall clean; `verify_migrations.py` passes (Alembic head 009).

## L. Git / CI
- Branch `darroyo083/goal-verifier-finalization` (Orca worktree), commits: 5424e8c (AB2 impl), fd79775 (dev pack+tests), a11c327 (correction), e124ef4 (V4 freeze), 90aec9c (pacing).
- CI: to be run on the merged master push (see final steps).

## M. Final Decision
**B — V4 FAILED / VERIFIER RESEARCH CLOSED**

## N. Product Next Step
Close the verifier-reliability research line. The attribute-binding verifier achieves the core reliability invariant (0 false supports) but is not production-ready: it over-rejects legitimate answers (retention ~71–85%, below the 90% gate), and the model is non-deterministic even at temperature 0. Recommend moving DocuMind to the next product milestone rather than another verifier architecture experiment.
