# Identity Isolation Audit — 2026-04-19

**Author:** Claude Code (Brief 1b Task 4)
**Reviewer:** Toby Fletcher
**Status:** Draft, informational. Acting on recommendations is a follow-up.

## Executive summary

The Deek identity layer shipped in Brief 1a is structurally sound: the
two source files (`DEEK_IDENTITY.md`, `DEEK_MODULES.yaml`) are the only
sources of Deek's self-description, loaded once at process boot, and
hashed for deploy-parity checks. Isolation of the *identity content* is
tight. The blast radius concerns are upstream of identity — in the
deploy pipeline and in the web application's handling of build-time
constants.

Three findings, all medium severity, one of which is live on production
today.

| # | Finding | Severity | Effort |
|---|---|---|---|
| F1 | No branch protection on `master` | Medium | S |
| F2 | No CODEOWNERS file on identity-critical paths | Medium | S |
| F3 | 25 web route handlers inline `process.env.DEEK_API_KEY` at build time; same SWC-folding class as the 2026-04-19 regression | Medium-High | M |

Recommendations at the bottom. Nothing in this audit requires immediate
action unless Toby decides otherwise; the mitigations already in place
(deploy script + smoke test) prevent recurrence of the specific
regression.

---

## 1. Inventory

### 1.1 Repos with write access to identity files

A file-system search (`D:\claw\`) and repository metadata check
(`NBNEORIGIN/deek` via `gh api`) established:

| Repo | Branch | Write access | Notes |
|---|---|---|---|
| `NBNEORIGIN/deek` | `master` | Yes — any collaborator | Only repo on disk that contains `DEEK_IDENTITY.md`, `DEEK_MODULES.yaml`, or `core/identity/`. Repo is **public** (`isPrivate: false`) with `NBNEORIGIN` as the sole listed collaborator at audit time. |
| `NBNEORIGIN/deek` | any feature branch | Yes | Feature branches can modify identity files and merge without review. |
| Any other NBNE module repo | n/a | **No** | Identity files are not referenced, imported, symlinked, or duplicated in `manufacture`, `phloe`, `ledger`, `beacon`, `render`, or `crm` codebases. Module repos consume Deek via HTTP; they do not touch its source. |

**Net:** only the Deek repo itself is a write vector. No module repo
can modify Deek's sense of itself through any supply-chain path.

### 1.2 CI/CD paths that can modify identity files

- **GitHub Actions:** none. `.github/` does not exist in the repo.
- **Deployment mechanism:** manual SSH + `deploy/build-deek-api.sh` /
  `deploy/build-deek-web.sh`. Deploys are triggered by a human running
  the script, not by a commit.
- **Post-deploy smoke test:** wired into both deploy scripts as of
  Brief 1b (this PR). Fails the deploy if `identity_hash` or
  `declared_modules` drift from the committed golden fixture without a
  matching `identity-fixture-update:` PR.

### 1.3 Shared deploy infrastructure

- Hetzner host `178.104.1.152` hosts Deek alongside every other NBNE
  module's production container. Shared:
  - Docker daemon + `/var/lib/docker`
  - nginx + Let's Encrypt
  - `/opt/nbne/` directory tree (per-module subdirs)
- **Not shared:** Postgres databases (each module has its own or uses a
  dedicated schema), env files (`/opt/nbne/<module>/deploy/.env`),
  Docker networks.
- **Identity-relevant:** none of the other modules can modify Deek's
  `/opt/nbne/deek/DEEK_IDENTITY.md` or `DEEK_MODULES.yaml` unless they
  escape their container and gain root on the host, at which point
  identity isolation is not the threat model.

### 1.4 Shared configuration

- `CLAUDE.md`, `NBNE_PROTOCOL.md`, and `LOCAL_CONVENTIONS.md` are
  vendored into the Deek repo from the `nbne-policy` repo via
  `scripts/sync-policy`. Identity files are NOT part of the vendored
  bundle — they are Deek-only.
- Multiple env-variable naming conventions co-exist (`DEEK_API_KEY` /
  `CLAW_API_KEY` / `CAIRN_API_KEY`) during the Cairn → Deek rename.
  Both sides of the fence are read by the API (`verify_api_key` checks
  all three) — this is not an identity concern but is adjacent.

---

## 2. Branch protection state

Queried `gh api repos/NBNEORIGIN/deek/branches/master/protection`
on 2026-04-19 at 13:00 UTC:

```
{"message":"Branch not protected","status":"404"}
```

**Current state:**

- `master` branch: **unprotected**
- Required pull request reviews: **none**
- CODEOWNERS file: **does not exist**
- Status check requirements: **none**
- Force-push protection: **none**
- Signed-commit requirement: **none**
- Admin bypass: N/A (no protection to bypass)

Anyone with push access (currently `NBNEORIGIN` only) can force-push to
`master`, merge a direct commit without review, or delete the branch.
For a public repo hosting a production-critical memory layer, this is
the biggest single gap surfaced by this audit.

---

## 3. Root causes of the 2026-04-19 session

Two distinct mechanisms surfaced in the same session. Pinning them
separately because the remediations differ.

### 3.1 AMI misclassification

**Symptom:** After Brief 1a shipped, `GET /api/deek/identity/status`
reported AMI as unreachable (`ConnectError: Name or service not
known`). Deek began answering questions like "what modules can you
access?" by omitting AMI or flagging it as offline.

**Pinpoint:** AMI was declared in `DEEK_MODULES.yaml` as a peer
service with `base_url: https://ami.nbnesigns.co.uk`. No such host
exists — AMI is a Postgres schema (`ami_*` tables) inside Deek's own
DB, populated by the Manufacture module's SP-API integration and
queried by Deek in-process via the `query_amazon_intel(sql)` tool.

**Why it shipped that way:** Brief 1a drafted the initial
`DEEK_MODULES.yaml` against the `DEEK_MODULES.md` prose doc (which
lists AMI as a domain/capability) and the presence of `core/amazon_intel/`
in the source tree. Neither of those is evidence that AMI is deployed
as a peer HTTP service, but the draft didn't test the assumption by
probing the URL before merging. The identity layer then correctly
exposed the misclassification.

**Characterisation:** this is NOT an "identity layer broke something"
failure — it's an "identity layer did its job and surfaced a data-model
error that had been invisible." Brief 1a's pre-flight step 4
("reproduce today's bug") was performed on a live production system
already running with the wrong mental model; the test confirmed what
the model said was true, rather than what the architecture actually
is.

**Fix already landed:** commit `20a52b0` removed AMI as a peer module
and updated Manufacture's `when_to_consult` to explicitly direct
Amazon queries through `query_amazon_intel`.

**Class of bug:** *content error in a version-controlled config file*.
Mitigated by the new smoke test (declared-modules drift detection) and
by requiring a human-reviewed PR for any identity-file change.

### 3.2 Next.js SWC constant-folding of `process.env.DEEK_API_KEY`

**Symptom:** After the new `/api/voice/chat/agent-stream` proxy route
was added (to route the /voice Chat tab through the full agent
pipeline), every chat request returned HTTP 502. Access logs showed
the Next.js proxy getting 401 Unauthorized from the backend.

**Pinpoint:** Next.js 14 (with SWC) inlines `process.env.X` into the
compiled route handler as a string literal at build time. When the
Docker build ran without `--build-arg DEEK_API_KEY=$REAL_KEY`, the
Dockerfile's default ARG value (`deek-dev-key-change-in-production`)
got folded into the bundle:

```js
// /app/.next/server/app/api/voice/chat/agent-stream/route.js
apiKey:"deek-dev-key-change-in-production"
```

Runtime environment on the container had the correct key, but the
bundle never read it. Wrapping the env lookup in a function called
inside the request handler was also folded — SWC constant-folds
`process.env.X` regardless of call depth when the value resolves at
build time.

**Why it shipped that way:** the Dockerfile ARG had a placeholder
default specifically because "the runner stage env vars override at
runtime for any values that Next reads lazily." That assumption is
wrong — Next.js does NOT read lazily for server-side route handlers.
The placeholder was a foot-gun designed in.

**Fix already landed:**
- Commit `9fde328` removed the ARG default and added a `RUN test` step
  that fails the build if `DEEK_API_KEY` is missing or set to the old
  placeholder.
- Commit `d6b81e2` added `deploy/build-deek-web.sh` which reads
  `DEEK_API_KEY` from `deploy/.env` and passes it as a build-arg,
  mirroring `build-deek-api.sh`. Post-build it greps the compiled
  bundle for the placeholder string and fails if found.
- Brief 1b Task 5 added the same bundle-placeholder check to the
  standalone smoke test so it runs on every future deploy.

**Class of bug:** *build-time secret injection with no post-build
verification*. Broader than just `DEEK_API_KEY` — see F3 below.

### 3.3 What the brief got wrong about the root cause

The Brief 1b draft framed 3.1 as "a mobile UX deploy caused a
capability regression" — but the mobile UX deploy that day was
unrelated. It was the Brief 1a identity deploy itself that *exposed*
the AMI misclassification. The bug pre-existed; the layer just made it
visible. Important distinction because "mobile UX deploys can break
Deek's self-model" would have led to the wrong remediation.

---

## 4. Finding F3 — web bundle env inlining blast radius

A grep across `web/src/app/api/**/route.ts`:

```
D:\claw\web\src\app\api\  →  25 files reading process.env.* at module scope
```

Sample files showing the pattern that caused the 2026-04-19 regression:

```ts
// web/src/app/api/chat/route.ts
const CLAW_API_URL = process.env.CLAW_API_URL || 'http://localhost:8765'
const DEEK_API_KEY = process.env.DEEK_API_KEY || ''
```

```ts
// web/src/app/api/social/[...path]/route.ts
const CLAW_KEY = process.env.DEEK_API_KEY
  || process.env.DEEK_API_KEY
  || 'deek-dev-key-change-in-production'  // ← placeholder as fallback literal
```

All 25 files will have whatever value `DEEK_API_KEY` / `CLAW_API_KEY`
held at `npm run build` time folded into their compiled output. The
new `deploy/build-deek-web.sh` passes the real key as a build-arg, so
TODAY the bundle is correct. But:

- Any ad-hoc `docker build` without the build-arg reintroduces the bug
- Any new route handler following the existing pattern inherits the
  vulnerability silently
- The `social` route's fallback uses the placeholder LITERAL as a
  `||` default, which means it will ship the placeholder string even
  if the build-arg is passed correctly but happens to evaluate to a
  falsy value for some reason. This is redundantly vulnerable.

**Blast radius:** 25 Next.js route handlers, each one a possible 401
at runtime.

**Current mitigations:**
- `deploy/build-deek-web.sh` is the only blessed build path and
  enforces the build-arg
- The Dockerfile itself refuses to build with a missing or placeholder
  key
- Brief 1b Task 5 asserts no placeholder in the compiled bundle,
  post-deploy, for at least the `agent-stream` route

**Gap:** Task 5 only checks `agent-stream`. A new route handler with
a baked placeholder from a non-blessed build path wouldn't be caught
until it received traffic.

---

## 5. Recommendations

Ordered by cost/benefit. Effort scale:
- **S** — under 30 min
- **M** — 1–3 hours
- **L** — half a day or more

### R1 — Add CODEOWNERS requiring Toby on identity paths *(S)*

```
# .github/CODEOWNERS
/DEEK_IDENTITY.md        @tobyfletcher
/DEEK_MODULES.yaml       @tobyfletcher
/core/identity/**        @tobyfletcher
/tests/smoke/**          @tobyfletcher
```

Lightweight. Even without branch protection, `CODEOWNERS` is surfaced
in PR review UIs and is the minimum documentation of "who has to look
at identity changes."

### R2 — Enable branch protection on `master` *(S)*

```bash
gh api repos/NBNEORIGIN/deek/branches/master/protection \
  --method PUT --input - <<EOF
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": { "required_approving_review_count": 1 },
  "restrictions": null
}
EOF
```

Makes `CODEOWNERS` enforceable. Allows admin bypass so Toby can still
push directly for solo emergency work. Pairs naturally with R1.

### R3 — Expand Task 5 to all web routes *(M)*

Extend `test_identity_deploy.py` to grep **every** compiled route
handler (`/app/.next/server/app/api/**/route.js`) for the placeholder
string — not just `agent-stream`. Also grep for other known-sensitive
env var patterns (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`DEEK_JWT_SECRET`) to catch future additions.

Also add a lint rule (or a pre-commit script) that flags module-level
`process.env.X` reads in new route handlers, pointing at the safer
pattern of reading inside the request handler even though SWC folds
both — because it's a signal to the reviewer that the env var IS an
inlined constant and needs a build-arg, rather than a runtime-read
variable.

### R4 — Remove the placeholder-as-fallback in `social/[...path]/route.ts` *(S)*

```ts
// current, line 15:
const CLAW_KEY = process.env.DEEK_API_KEY
  || process.env.DEEK_API_KEY
  || 'deek-dev-key-change-in-production'

// recommended:
const CLAW_KEY = process.env.DEEK_API_KEY || ''
```

If the key is missing, failing with an empty-string-sent-as-header is
more honest than shipping the placeholder. Also remove the duplicated
`|| process.env.DEEK_API_KEY` — looks like a typo where one branch
should have been `CLAW_API_KEY`.

### R5 — Single env-read helper for all web routes *(M)*

Refactor the 25 route files to use `@/lib/deekConfig.ts`:

```ts
// web/src/lib/deekConfig.ts
export function deekConfig() {
  return {
    apiUrl: process.env.DEEK_API_URL || process.env.CLAW_API_URL || 'http://localhost:8765',
    apiKey: process.env.DEEK_API_KEY || process.env.CLAW_API_KEY || '',
  }
}
```

Doesn't defeat SWC folding — but it consolidates the inlined values
to one place, makes R3 easier (grep the helper, not 25 files), and
provides a single seam for future changes.

### R6 — Consider moving identity files to `nbne-policy` *(L)*

Currently identity is Deek-owned: any Deek collaborator can change
NBNE's sense of itself. If Deek becomes a product sold to external
customers (the roadmap implies this), identity files should live in
a tenant-owned space, not ship with the Deek binary.

**Not recommended for now** — premature. Flagging for the moment
external customers land.

---

## 6. What this audit did not cover

- **Runtime tampering.** An attacker with RCE inside the Deek
  container could write `/app/DEEK_IDENTITY.md` at runtime. The
  assembler loads once at import and does not re-read, so the next
  restart would reset — but requests between tamper and restart would
  see poisoned identity. Out of scope: we assume container RCE is a
  higher-severity incident than identity spoofing, and the identity
  layer does not claim to be a defence against it.
- **Memory layer.** Explicitly out of scope per Brief 1b.
- **Downstream consumers trusting Deek's identity claims.** No module
  currently consults `/api/deek/identity/status`. If they start to,
  separate threat-model work is needed.

---

*End of audit.*
