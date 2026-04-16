# Development Discipline & Architecture Reference

**Status:** Working draft — point-in-time snapshot
**Date:** 15 April 2026
**Author:** Toby Fletcher (with Claude)
**Scope:** NBNE module ecosystem — the central brain (currently *Deek*, proposed rename *Deek*) and its connected modules (Manufacture, Render, Ledger, Phloe, CRM, AMI, Beacon)

---

## 1. Why this document exists

We have a growing estate of interconnected web applications, and the way we develop them has started producing failures that are not bugs in any one app — they are failures of **discipline and architecture**. This document captures the problem as it stands today, the proposed solution direction, and the open decisions, so we have a stable reference point to refer back to as we execute.

This is a snapshot, not a finished policy. It supersedes nothing yet. It is the input to the work, not the output.

---

## 2. The symptom that prompted this

On the evening of 14 April 2026, a routine update to the **Manufacture** app caused **Deek** to roll back to an earlier version, losing functionality that had been working that morning.

This is not a one-off. Symptoms of the same underlying problem include:

- Claude Code chat sessions that begin work on one module and end up partly modifying a different module or the brain
- Changes intended to be local to one module producing side-effects in another
- Inconsistent state across `.env` files referring to the brain by three different names (`deek`, `cairn`, `deek` proposed)
- General difficulty knowing "what is the current state of X module"

These are not separate problems. They share a root cause: **the modules and the brain are not properly isolated at the filesystem, repository, or process levels**, and the AI development workflow we use to build them is not constrained to respect the boundaries we have on paper.

---

## 3. Diagnosis — three plausible mechanisms for the rollback

The Manufacture-edit-rolls-back-Deek symptom is consistent with one or more of:

1. **Shared physical location.** Deek code lives inside the Manufacture repository (or vice versa), or one repo vendors the other as copied source. A `git pull` or push in Manufacture's tree overwrites Deek files.
2. **Shared deploy artefact.** A single `docker-compose.yml` or deploy script on Hetzner rebuilds or restarts Deek from a pinned tag whenever any module deploys, and that pin is stale.
3. **Agent drift.** The Claude Code session for Manufacture had Deek's source on its filesystem and edited it during the session, then committed both.

**Action:** confirm which mechanism (or combination) is biting before designing the migration. Run from each Hetzner module root:
```
find . -name "*cairn*" -not -path "*/node_modules/*" -not -path "*/.git/*"
```
And inspect any shared `docker-compose*.yml` for service definitions referencing Deek.

The architectural fix below addresses all three mechanisms regardless.

---

## 4. Architectural principles (already established, restated for clarity)

These are not new. They have been articulated in earlier conversations and exist in user memory. They are restated here because they have not been operationally enforced.

1. **No module accesses another module's database directly.** All cross-module data flow goes through the owning module's HTTP API.
2. **The brain (Deek/Deek) is the memory layer above the modules.** It does not own business data. Each module owns its own data and exposes a context endpoint to the brain.
3. **The AI accesses modules only via a controlled tool-use API layer.** No direct database access from the AI to any module.
4. **Each module gets its own dedicated AI development agent**, constrained to that module's API surface, following a per-module `MODULE_PROTOCOL.md`.
5. **The code stays in Northumberland.** Sovereignty over code, data, and infrastructure is a non-negotiable constraint.

What is missing is **enforcement at the filesystem and deploy level**, not just at runtime.

---

## 5. The two questions we are solving

### Q1 (hard) — How do we use Claude Code effectively to develop these modules in a compartmentalised way?

### Q2 (easier) — How do we rename the brain from Deek to Deek across an estate where references to *deek*, *cairn*, and *deek* now coexist in `.env` files, code, hostnames, and config across multiple repositories?

---

## 6. Proposed solution to Q1 — Claude Code compartmentalisation

### 6.1 The mental model shift

Stop thinking *"Claude Code is helping me build my system."* Start thinking *"each repo has its own dedicated Claude Code specialist who is forbidden from working anywhere else."* Different trades for plumbing and electrics.

### 6.2 Six concrete mechanics

1. **One CC session = one repo. Always.**
   Launch `claude` from the repo root, never from a parent directory containing siblings. CC's filesystem tools are anchored to the working directory and the discoverable tree below it. If it cannot see a sibling module's source, it cannot edit it.

2. **`CLAUDE.md` at the root of every repo, doing real enforcement work.**
   Not a generic doc. A sharp, short scope statement that CC reads automatically at session start. Template wording:
   > *"You are the [Module] agent. You may modify only files in this repository. You may not modify Deek (the brain), nor any sibling module. You communicate with Deek via its public HTTP API as documented in `docs/DEEK_CLIENT.md`. If a task requires changes to Deek's API surface or to another module, STOP and tell the user — that requires a spanning brief, not action by you."*

3. **The spanning-brief pattern for cross-cutting changes.**
   When a real change crosses repos (e.g. Deek needs a new context endpoint that Manufacture will consume), it is designed *in chat with Claude in conversation* before any agent touches code. Output is **two separate briefs**, executed in **two separate CC sessions** in **two separate repos**, in a defined order: producer first (Deek ships and deploys the new endpoint with versioned API), then consumer (Manufacture upgrades its client and uses it).

4. **Terminal/window discipline.**
   Each module gets its own VS Code window or tmux session, named for the module. When you switch modules, you close one and open another. No "let me just quickly check Deek while I'm here" — that impulse is exactly how the current cross-wiring happens.

5. **Per-repo guardrails — belt and braces.**
   - Pre-commit hook in each repo that fails if any commit touches a path containing another module's name
   - CI per repo (independent — no shared monorepo build)
   - Contract tests on both sides of every API boundary
   The discipline should prevent ~95% of incidents; the gates catch the rest.

6. **Chat hygiene.**
   When a chat with Claude starts drifting from "Manufacture brief" into "while we're at it, let's also tweak Deek," split the conversation. Same rule applies to CC sessions, more strictly: never let one session span modules.

### 6.3 Architectural prerequisites (must be true for the above to work)

- **One repo per module. One repo for Deek. No exceptions.** The earlier Phloe monorepo pattern was about Phloe's *internal* tenant modules — a single product. Deek/Deek, Manufacture, Render, Ledger, Phloe, CRM, AMI, Beacon are *separate products*. They get separate repos.
- **Deek never sees module source code.** It calls `GET /api/cairn/context` (or `/api/deek/context` post-rename) on each module over HTTP. That is the only coupling.
- **Modules consume Deek via a thin, versioned client SDK** — published as a Python/TypeScript package (private GitHub Packages registry is fine). Never vendored as copied source. API changes = SDK version bump = explicit opt-in upgrade.
- **Each module has its own systemd service, its own deploy pipeline, its own code root on Hetzner** (e.g. `/srv/deek`, `/srv/manufacture`, `/srv/render`). Separate GitHub Actions per repo. Deploying one cannot touch another's files.
- **API contracts are the single source of truth.** Each module ships an OpenAPI spec in its repo. Breaking changes = major version bump = coordinated upgrade.

---

## 7. Working patterns we have already developed

Independent of the architectural fix in §6, three working patterns have emerged from practice. They are documented here so they can be evaluated, named, and refined rather than remaining tacit.

### 7.1 Pattern A — The memory layer (RAG + wiki + reference)

A semantic memory layer combining:
- pgvector / BM25 hybrid retrieval over conversation and decision history
- Karpathy-style wiki articles capturing structured knowledge (architectural decisions, runbooks, domain vocabulary)
- A reference layer on top providing canonical pointers (which document is authoritative for which question)

**Role in the framework:** Pattern A is the *substrate* on which Pattern C depends. A handover summary that triggers a fresh CC session is only useful if the new session can rebuild context by *retrieving* — not by being re-told. Pattern A is the retrieval mechanism.

**Status:** Built and operational within Deek/Deek. Needs to be made *queryable by the per-module CC agents*, not only by the central brain.

### 7.2 Pattern B — The development prompt refinement loop

The standard loop for non-trivial development work:

1. Toby outlines the development requirement in conversation with Claude
2. Claude formalises and structures it into a draft brief
3. Brief is passed to Claude Code (typically Opus) for technical review
4. CC's review feedback is passed back to Claude in conversation for sign-off and minor updates
5. Refined brief returns to CC for a final review pass
6. CC implements

**Status:** Working well at the per-repo level. This is the documented standard for any change touching more than a handful of files.

**Where it fits in the framework:** Pattern B is the mechanism by which spanning briefs (§6.2 item 3) are produced. Cross-repo work follows Pattern B *twice* — once per repo, in producer-then-consumer order — never in a single combined session.

**Refinement needed:** The pattern should be formalised with explicit role names ("conversation Claude" vs "executing CC") and a template for the brief structure. The manufacture briefs (label printing, SP-API automation, sales velocity) are working examples that should be canonicalised as templates.

### 7.3 Pattern C — Chat-length cutoff with handover summary

When a chat approaches context limits, produce a summary / handover prompt to seed a fresh session.

**Status:** Not working reliably. The failure mode is diagnostic.

**The failure mode in detail:** Fresh sessions exhibit basic operational gaps — for example, not knowing how to SSH into Hetzner or the local server, despite this being documented in the project. When the AI is directed to the documentation, it resolves the gap immediately and correctly.

**Diagnosis:** This is *not* a context-length problem. It is a **retrieval problem**. The documented knowledge exists and is correct. The AI in a fresh session does not know to look for it.

**Implication:** The fix is not "write better handover summaries" (though that helps at the margin). The structural fix has two parts:
- **Operational essentials must be force-loaded at session start**, not retrieved on demand. SSH targets, deploy commands, service names, common gotchas. This is what `CLAUDE.md` is for (see §6.2 item 2).
- **Deeper context must be retrievable on demand**, not summarised in advance. This is what Pattern A (the memory layer) is for.

A good `CLAUDE.md` plus a queryable memory layer makes Pattern C work — because the new session can always find what it needs, either pre-loaded or retrievable. Without those substrates, Pattern C will keep failing in the same way.

### 7.4 How the three patterns combine

```
                          ┌─────────────────────┐
                          │   Pattern A         │
                          │   Memory layer      │
                          │   (RAG + wiki +     │
                          │    reference)       │
                          └──────────┬──────────┘
                                     │ retrievable on demand
                                     ▼
   ┌──────────────────┐    ┌─────────────────────┐    ┌────────────────┐
   │  CLAUDE.md at    │───▶│   Pattern B         │───▶│  Implementation│
   │  repo root       │    │   Brief refinement  │    │  by CC         │
   │  (force-loaded)  │    │   loop              │    │                │
   └──────────────────┘    └─────────────────────┘    └────────────────┘
                                     ▲
                                     │ when context exhausts
                          ┌──────────┴──────────┐
                          │   Pattern C         │
                          │   Handover to       │
                          │   fresh session     │
                          │   (now actually     │
                          │    works)           │
                          └─────────────────────┘
```

The §6 architectural work and the Pattern A/B/C work are not separate streams — they are the same effort viewed from two angles. §6 is about the *boundaries between modules*. §7 is about the *flow of context within and across sessions*. Both need to hold for the system to be developable at scale.

---

## 8. Proposed solution to Q2 — Renaming Deek to Deek

### 8.1 Why rename

- Voice ASR consistently misinterprets "Deek" as Ken / Kern / Karen. For a brain you talk to, this is a hard usability defect.
- Staff have not adopted the name.
- "Deek" — Anglo-Romani / Northumbrian dialect verb meaning *"to look at"* — is monosyllabic, phonetically distinct, has no homophones in standard English, and the meaning is almost too on-the-nose for an intelligence layer.
- Domain and trademark are available (verify before announcement).

The Deek metaphor is genuinely good (a marker built by everyone who came before, accumulated knowledge, belongs to the landscape). It is being retired for **operational** reasons, not because the meaning was wrong.

### 8.2 Principles

- **Skip the intermediate.** Migrate `deek → deek` and `cairn → deek` in a single sweep. Two old names, one new name.
- **Deprecate, don't break.** Add new names alongside old, switch consumers one at a time, remove old names after a grace period.
- **Do this AFTER the Q1 repo separation.** Renaming a cross-wired estate compounds the chaos.

### 8.3 Inventory — must run first

A single ripgrep across all repos:
```
rg -i "deek|cairn|DEEK|DEEK" --type-not lock
```
Categorise hits:
- Code identifiers (classes, modules, variables)
- Env var names (`DEEK_API_URL`, `DEEK_API_KEY`, etc.)
- Hostnames (`deek.nbnesigns.co.uk`)
- Database names (`cairn_db`)
- Systemd unit names
- Docker container/service names
- API paths (`/api/cairn/*`)
- Log prefixes
- Documentation, READMEs, comments
- User-facing strings

The env vars and hostnames are the highest-risk because they are cross-repo coupling points.

### 8.4 Phased migration

**Phase 0 — Pre-work**
- Buy `deek.ai`, `deek.app`, `usedeek.com`, `deek.co.uk` before announcing internally
- Trademark check class 42 (software) and 35 (business services)
- Document the Berwick dialect provenance somewhere referenceable — useful later for marketing

**Phase 1 — Deek's own repo**
- Rename internally: code identifiers, package name, log prefixes
- Primary hostname becomes `deek.nbnesigns.co.uk`
- Keep `deek.nbnesigns.co.uk` as a DNS CNAME alias pointing to the same service
- API responds to both `/api/deek/*` and `/api/cairn/*` paths during the migration window
- **Database name stays `cairn_db` for now** — internal, low-value to rename, can be deferred indefinitely or done in a later maintenance window

**Phase 2 — Each module, one at a time**
- Rename consumer SDK from `cairn-client` to `deek-client` (publish new versioned package; `cairn-client` becomes a thin re-export shim for one release cycle, then deprecated)
- Update env vars: introduce `DEEK_API_URL` / `DEEK_API_KEY`, keep `DEEK_API_URL` as a fallback for one release, then remove
- Order: Manufacture first (most active), then Render, Ledger, Phloe, CRM, AMI, Beacon

**Phase 3 — Cleanup**
- Remove `DEEK_*` env var fallbacks
- Remove `/api/cairn/*` API path aliases

**Phase 4 — DNS retirement**
- Drop `deek.nbnesigns.co.uk` DNS alias after 30 days of zero traffic on it (log and verify before removing)

**Phase 5 — Optional database rename**
- `ALTER DATABASE cairn_db RENAME TO deek_db;` plus connection-string update
- ~10 minutes of downtime; defer until convenient

### 8.5 Tooling for the rename

For each repo, produce a `RENAME_BRIEF.md` listing exactly which files change and which substitutions to make, with explicit notes on which references are aliases (keep) and which are full renames (replace). Execute in that repo's CC session only. Verify with a fresh ripgrep before committing.

Total estimate: **2–3 focused evenings spread over a fortnight**, mostly verification rather than typing.

---

## 9. Recommended order of operations

1. **Diagnose the rollback** — confirm whether mechanism 1, 2, 3 (or combination) from §3 is biting
2. **Repo separation, module by module** — start with Manufacture as the template:
   - Extract into its own repo
   - Set up its own deploy pipeline (independent GitHub Action)
   - Drop `CLAUDE.md` at root with the scoped agent prompt
   - Add the pre-commit hook for cross-module path protection
   - Publish the consumer SDK
3. **Repeat for Render, Ledger, Phloe, CRM, AMI, Beacon**
4. **Repo separation for Deek itself last** — because everything depends on its API surface
5. **Stabilise — run the new pattern for one to two weeks** with no rename activity. Confirm cross-wiring incidents have stopped.
6. **Then execute the rename** per §8.4, against now-clean repos with stable boundaries

---

## 10. Open decisions

- [ ] Which of the three rollback mechanisms (§3) is actually causing the symptom? Diagnose before designing migration scripts.
- [ ] Domain and trademark check on "Deek" — confirm available in classes 42 and 35.
- [ ] Consumer SDK packaging: GitHub Packages (private) vs. self-hosted PyPI/npm registry?
- [ ] CI provider — continue with GitHub Actions per repo, or introduce something self-hosted on the sovereign server?
- [ ] Pre-commit hook implementation — Husky (Node-based) vs. native Git hooks vs. `pre-commit` framework (Python)?
- [ ] Does HAL (Pi 5 voice appliance) need its own repo and its own scoped agent under this scheme? (Probably yes.)
- [ ] How does the Windsurf agent vs Claude Code agent distinction map onto this? (User memory references both.)
- [ ] How do per-module CC agents query Pattern A's memory layer? (HTTP endpoint on Deek? Read-only SDK method? MCP server exposing the memory as a tool?)
- [ ] Should Pattern B (the brief refinement loop) be canonicalised as a templated workflow with named phases, or kept as a tacit habit?
- [ ] What is the minimum viable `CLAUDE.md` payload for operational essentials? SSH targets + deploy commands + service names is the obvious core — what else must be force-loaded vs retrievable?

---

## 11. What this document does not address

- The detailed `CLAUDE.md` template wording per module (separate deliverable — **next**)
- The detailed `RENAME_BRIEF.md` template per repo (separate deliverable)
- The pre-commit hook script itself (separate deliverable)
- The consumer SDK design and versioning policy (separate deliverable)
- The OpenAPI spec format and contract test framework choice (separate deliverable)
- The brief structure template canonicalising Pattern B (separate deliverable)
- The memory-layer query interface for per-module CC agents (separate deliverable, depends on §6 repo separation)

These follow once the framework above is agreed.

---

## 12. Glossary

| Term | Meaning |
|---|---|
| **Deek** | Current name of the central brain / memory layer. Being retired. |
| **Claw** | Original generic name. Legacy references still exist. To be retired in same migration. |
| **Deek** | Proposed new name. Anglo-Romani / Berwick dialect verb meaning "to look at". |
| **Module** | A separate web application owning its own domain data (e.g. Manufacture, Render, Ledger, Phloe, CRM, AMI, Beacon). |
| **Brain** | The central memory/intelligence layer — Deek, soon Deek. |
| **Spanning brief** | A coordinated change specification that crosses repository boundaries, designed in conversation before any agent touches code, executed as separate per-repo briefs in defined order. |
| **MODULE_PROTOCOL.md** | Per-module specification of API surface, events, dependencies, and agent boundaries. |
| **CLAUDE.md** | Per-repo scope document automatically loaded by Claude Code at session start. |
| **WIGGUM** | Overnight autonomous loop concept for Deek/Deek (per user memory). |
| **Sovereignty principle** | All code, data, and infrastructure remain on NBNE hardware in Northumberland. Non-negotiable. |
| **Pattern A** | The memory layer (RAG + Karpathy wiki + reference layer) that allows context to be retrieved on demand rather than re-explained. |
| **Pattern B** | The development brief refinement loop: conversation Claude drafts → CC reviews → conversation Claude refines → CC implements. |
| **Pattern C** | The chat-length cutoff and handover-to-fresh-session mechanism — currently failing due to retrieval, not context-length, problems. |

---

*End of document. This is a snapshot of thinking on 15 April 2026 and will be superseded by the operational documents (CLAUDE.md template, RENAME_BRIEF.md template, pre-commit hook, SDK design) once those are produced.*
