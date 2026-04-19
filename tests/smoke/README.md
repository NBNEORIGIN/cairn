# Smoke tests

Post-deploy smoke tests for Deek. These are NOT unit tests — they hit a
live deployment over HTTP and fail the deploy script on drift.

## Files

- `golden_identity.json` — frozen snapshot of the expected
  `/api/deek/identity/status` response on Hetzner. Captured at the
  moment Brief 1b shipped.
- `test_identity_deploy.py` — runnable post-deploy smoke test. Takes
  `--url BASE` (required). Compares live state to the golden fixture.
  Exit 0 on pass, 1 on fail. Structured findings go to stderr for log
  scraping; human-readable output goes to stdout.
- `.gitkeep` — reserved by Brief 1a (can be removed once the directory
  has other files — which it now does).

## Usage

```bash
# From any machine that can reach Hetzner:
python tests/smoke/test_identity_deploy.py --url https://deek.nbnesigns.co.uk

# From the Hetzner host itself (the build-deek-*.sh scripts do this
# automatically as their last step):
python /opt/nbne/deek/tests/smoke/test_identity_deploy.py \
  --url https://deek.nbnesigns.co.uk
```

The post-deploy bundle check (Task 5) requires running on the Hetzner
host with Docker access. When run from a machine that can't see the
web container, that check is skipped cleanly — it does not fail the
overall smoke.

## What the smoke test checks

| Check | Rule |
|---|---|
| `identity_hash` | Must match golden fixture exactly. |
| `declared_modules` | Must match golden fixture exactly (order-insensitive). |
| `reachable` modules | Must be a SUPERSET of `expected_reachable_on_hetzner`. Extras (e.g., `deek` self-probe) are tolerated. Missing any expected module fails. |
| Compiled bundle | No `"deek-dev-key-change-in-production"` literal in the web container's compiled route handlers. Only runs when Docker access is available. |

## Updating the fixture

When `DEEK_IDENTITY.md` or `DEEK_MODULES.yaml` changes legitimately, the
fixture MUST be updated — but in a **separate PR**, AFTER the identity
change has merged and been deployed to Hetzner. The sequence is:

1. PR #1 — change `DEEK_IDENTITY.md` or `DEEK_MODULES.yaml`. Merge.
2. Deploy `deploy/build-deek-api.sh full`. Smoke test WILL fail — that's
   expected.
3. PR #2 — titled `identity-fixture-update: <one-line reason>`. Body
   contains the output of `curl
   https://deek.nbnesigns.co.uk/api/deek/identity/status` as evidence.
   Replaces `golden_identity.json`. Merge.
4. Re-deploy. Smoke test now passes.

The two-PR discipline exists so fixture updates are always human-reviewed
against the live state, never bundled with the identity change that
caused them. A single PR that touches both identity source files AND the
fixture is refused in review.

## Why the Deek self-probe is excluded from expected_reachable

Deek's health endpoint is `https://deek.nbnesigns.co.uk/health`. When
Deek's probe fires at its own public URL, the request goes out through
the host network, back in through nginx, then to the API container —
the "hairpin" path. Cloudflare/nginx/conntrack can cause this to
intermittently return HTTP 502 even when Deek is plainly serving every
other request. Rather than fix the hairpin (which would require an
internal-DNS short-circuit and is out of scope for the identity layer),
we simply accept that `deek` may or may not be reachable from its own
probe and test only that the **six peer modules** are always reachable.
