# BUG-FIX BRIEF v2 — Validator leak + corpus contamination

**Target repo:** Deek (`D:\claw` / `NBNEORIGIN/deek`)
**Module:** core agent loop + memory indexer + protocol doc
**Consumer:** Claude Code (Deek CC session executes)
**Protocol:** `NBNE_PROTOCOL.md`
**Prerequisite:** Brief 1a.2 merged (canonical name, lowercase `a`)

**Reframed from v1 based on read-only recon (2026-04-22):**
- "Silent termination" is actually a **leak** — agent returns
  `"Validation failed:\n- CHECK 3: ..."` verbatim to the user. Fixing
  means replacing the leak with a user-safe message, not building
  retry+fallback from scratch (both exist at `core/agent.py:1742-1812`).
- **Zero chunks in the live DB match the known hallucinated paths.**
  Cleanup task is narrower than v1 thought — the contamination vector
  is `NBNE_PROTOCOL.md` lines 627-632 on disk, not indexed chunks.
- `salience_signals` is **write-only today** — nothing in the retriever
  reads it. A speculative-flag based on it is cosmetic until a reader
  lands. Scope cut: move that to a follow-up.

---

## Scope discipline

Two bugs, tight scope. Do not expand into adjacent improvements even if
tempting. Log adjacent issues as follow-ups.

---

## Bug 1 — Protocol doc self-contamination

`NBNE_PROTOCOL.md` lines 627-632 cite two non-existent paths
(`core/memory/brief_questions.py`,
`scripts/memory_brief/question_generator.py`) in prose, as a cautionary
example of a previous hallucination. On every reindex these back-tick
code paths enter the chunk store with no signal that they are
speculative. Next retrieval round surfaces them. Model treats them as
real. Validator catches. Loop fails.

**Fix:** replace the back-ticked paths with neutralised placeholders
that make the same cautionary point without looking like real code
citations. Example:

```
…hallucinating file paths (two invented module names that looked
plausible but did not exist on disk) that didn't exist, and being
blocked three times by the validator…
```

No mention of specific fake filenames. The lesson survives; the
contamination vector is removed.

Confirm on Hetzner with the recon SQL below that no OTHER chunks cite
these paths. Today's count is 0, but a reindex could change that
between now and when the fix lands.

```sql
SELECT COUNT(*) FROM claw_code_chunks
 WHERE chunk_content ~ 'brief_questions|memory_brief/question_generator';
```

Expected post-fix: 0. If >0, list ids + cleanup in the same PR.

---

## Bug 2 — Validator rejection leaks internal codes to the user

### Current behaviour (`core/agent.py`)

Three points of leak:

1. **Line 1736-1740 — hard_fail path** returns the raw
   `"Validation failed:\n- CHECK <n>: ..."` as the response.
2. **Line 1814-1817 — retries-exhausted** same raw failure text.
3. **Line 1161-1171 — GenerationTimedOut** yields `str(exc)` as the
   response body (adjacent leak pattern — fix in the same PR).

The retry loop (1742-1797) already fans out across model tiers using
`_build_validation_retry_prompt`. What's missing is (a) per-CHECK
guidance and (b) a user-safe final fallback.

### Task 2.1 — User-safe fallback message

Replace the three leak sites with a plain-language message. Template:

> I wasn't able to produce a confident response this time ({short
> reason}). Could you rephrase or narrow the question? I'll try again.

`{short reason}` mapping (keep additions here when new checks appear):

| CHECK | User-visible reason |
|---|---|
| CHECK 1 | "I described a tool call without actually running it." |
| CHECK 2 | "I refused rather than answered." |
| CHECK 3 | "I cited a file I couldn't verify." |
| CHECK 4 | "The draft didn't pass a tenant-isolation check." |
| CHECK 5 | "The response came back effectively empty." |
| CHECK 6 | "A file I wrote has a Python syntax error." |
| (multi) | "The draft failed multiple quality checks." |
| timeout | "The model took too long to respond." |

Never surface `CHECK N` codes, exception class names, or stack traces.

### Task 2.2 — Per-CHECK retry guidance

Extend `_build_validation_retry_prompt` in `core/agent.py` so the
retry prompt tells the model *which* check failed and *how to avoid
it*. For CHECK 3: "Your previous response cited a file path that does
not exist. Produce the response again without citing specific files
or paths unless you have verified they exist via a tool call."

One guidance string per CHECK. Shared helper, no per-call-site copy.

### Task 2.3 — Observability (extend model_response_audit)

**Do not create a second table.** Extend `model_response_audit`
(migration 0006) with:

```sql
ALTER TABLE model_response_audit
  ADD COLUMN IF NOT EXISTS validation_failures TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS validation_retry_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS validation_final_outcome TEXT;
  -- 'passed' | 'retry_succeeded' | 'retry_exhausted_fallback' | 'hard_fail'
```

The writer in `core/memory/response_audit.py` already receives a
`metadata` dict — pull `validation_failures`, `validation_retries`,
`validation_recovered` from it. A migration (0008) ships the column
additions.

---

## Out of scope (follow-ups)

- Speculative-flag plumbing in `salience_signals`. Column is
  write-only today — adding a flag without a retriever reader is
  cosmetic. Revisit when we add a chunk-type-aware retriever filter.
- Pre-response verification pass. CHECK 3 already does this. Moving
  it earlier in the pipeline is a latency/UX tradeoff worth its own
  brief, not this one.
- Full audit of the 60 wiki chunks that cite code paths. Most are
  real; the 2 known-bad ones aren't currently indexed. Sampling is a
  separate brief.

---

## Pass / fail gates

PASS:

1. `NBNE_PROTOCOL.md` no longer contains the back-ticked fake paths.
2. `SELECT COUNT(*) FROM claw_code_chunks WHERE chunk_content ~
   'brief_questions|memory_brief/question_generator'` = 0.
3. Agent loop, hard_fail + retries-exhausted + timeout paths, return
   a user-safe message (no `CHECK N`, no exception names).
4. `_build_validation_retry_prompt` includes per-CHECK guidance —
   test with a forced-CHECK-3 stub.
5. `model_response_audit` has the three new columns; a deliberately
   triggered validation failure produces a row with
   `validation_final_outcome != NULL`.
6. All existing tests pass.

FAIL:

- Any of the three leak sites still returns raw `CHECK N` to the user.
- New columns added to a fresh `validation_rejections` table instead
  of extending `model_response_audit`.
- NBNE_PROTOCOL.md patch that re-introduces the same filenames in
  different wording.

---

## Write-back

`update_memory(...)` per Step 4. Decision field: "Replaced Brief v1's
'build retry+fallback' with 'fix the leak' after recon showed retry
already exists. Zero chunks currently contaminated. Follow-up:
speculative-flag plumbing when retriever reader lands."
