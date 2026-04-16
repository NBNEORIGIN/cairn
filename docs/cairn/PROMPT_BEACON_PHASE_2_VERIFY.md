# Beacon Phase 2 Verification + Housekeeping

Phase 2 conversion pipeline wiring is built (5 commits, 16cdafa..3b49baf).
This session verifies it works end-to-end, commits outstanding housekeeping
files, and populates the live conversion action map.

Read first:

- `CLAUDE.md` in the beacon repo
- `INFRASTRUCTURE.md` in the beacon repo
- `docs/google_tag_installation.md` — just written in Phase 2

Standard Cairn protocol applies. Memory write-back with non-empty
`learned`, `project="beacon"`.

---

## Confirmed facts

- Beacon dev ports: 8017/3017
- Sub-account: `2028631064` (campaigns + conversion actions live here)
- MCC: `2141262231` (manager, never receives uploads)
- Three conversion actions exist in Google Ads (created 2026-04-15):
  1. `NBNE Signs — Contact Form` — offline import, qualified lead
  2. `Phloe — Contact Form` — offline import, qualified lead
  3. `NBNE — Phone Call Lead` — website call tracking (tag-based)
- `google-ads` pinned at 30.0.0 (API v20)
- Redis broker: `tporadowski/redis` portable at
  `C:\Users\zentu\tools\redis-win\redis-server.exe`
- Dependencies run in Docker — celery, google-ads, redis are NOT in the
  local Windows Python env. Management commands must run inside the
  Django container or a properly configured venv.

---

## The work — 4 outcomes

### Outcome 1 — Migrate and verify schema

Apply the new migration:

```bash
python manage.py migrate ads
```

Verify the `conversion_action_map` column exists on `beacon_google_ads_account`:

```bash
python manage.py shell -c "
from ads.models import GoogleAdsAccount
a = GoogleAdsAccount.objects.first()
print(f'conversion_action_map: {a.conversion_action_map}')
"
```

Should print `conversion_action_map: {}` (empty dict default).

Commit: not needed (migration already committed in 16cdafa)

### Outcome 2 — Populate conversion action map

Run against the live sub-account:

```bash
python manage.py beacon_list_conversion_actions --customer-id 2028631064
```

Verify the three actions from D-009 are visible. Then populate:

```bash
python manage.py beacon_list_conversion_actions --customer-id 2028631064 --populate
```

Verify it stuck:

```bash
python manage.py shell -c "
from ads.models import GoogleAdsAccount
a = GoogleAdsAccount.objects.get(customer_id='2028631064')
import json
print(json.dumps(a.conversion_action_map, indent=2))
"
```

Should show three entries mapping action names to numeric IDs.

Paste the output of `beacon_list_conversion_actions` in the memory
write-back as a decision record (D-010).

### Outcome 3 — Verify cairn context endpoint

```bash
curl -s -H "Authorization: Bearer $CAIRN_API_KEY" http://localhost:8017/api/cairn/context | python -m json.tool
```

Must return the full context JSON (module, spend, performance, scheduler,
health blocks), NOT a 401. The fix was adding `@authentication_classes([])`
to bypass DRF's global JWTAuthentication (commit 3d853a2).

If it still returns 401: check that the middleware stack in
`config/settings/base.py` hasn't been overridden by a local settings file,
and that `CAIRN_API_KEY` in the environment matches what you're sending.

### Outcome 4 — Dry-run the conversion pipeline

```bash
python manage.py beacon_dry_run_conversion --customer-id 2028631064
```

Should print:
1. A fake GclidCapture ID
2. A fake Conversion ID
3. The upload payload JSON with a resolved `conversion_action_id`
   (numeric, not the action name)
4. The full resource name: `customers/2028631064/conversionActions/NNNN`
5. "Rolling back transaction — no rows persisted"
6. "Dry run complete. Full pipeline verified."

If it fails with "empty conversion_action_map": Outcome 2 didn't run
or didn't persist. Re-run `--populate`.

Paste the dry-run payload in the memory write-back.

---

## Housekeeping — commit outstanding files

The architecture decoupling session (2026-04-16) left several files
untracked in the beacon repo. Commit them now:

### Architecture / policy files

```
CLAUDE.md               — scoped agent identity for Beacon
INFRASTRUCTURE.md       — SSH, deploy, containers
core.md                 — domain context
NBNE_PROTOCOL.md        — vendored universal protocol
LOCAL_CONVENTIONS.md    — vendored paths/ports/naming
DEEK_MODULES.md         — vendored module API contracts
scripts/sync-policy.ps1 — Windows policy sync script
scripts/sync-policy.sh  — Linux policy sync script
```

Commit: `chore(beacon): add architecture and vendored policy files`

### OAuth callback fix

`backend/ads/oauth_views.py` has an uncommitted one-line change:
OAuth callback now redirects to the Django admin detail page for the
account instead of `/tenants/{tenant_id}` (which doesn't exist in the
frontend yet).

Commit: `fix(beacon): oauth callback redirects to admin detail page`

### Gitignore celerybeat

`backend/celerybeat-schedule.bak`, `.dat`, `.dir` are celerybeat
scheduler state files. Add them to `.gitignore`:

```
backend/celerybeat-schedule.*
```

Commit: `chore(beacon): gitignore celerybeat schedule files`

---

## What NOT to do

- Do not deploy Beacon to Hetzner — dev-only for now
- Do not install beacon.js or the Google tag on any live website
- Do not create new conversion actions in Google Ads
- Do not change the Celery schedule or job cadence
- Do not start the Tag Health Monitor (separate brief at
  `docs/BEACON_TAG_HEALTH_MONITOR_CC_PROMPT.md`)

## Status report

After all outcomes + housekeeping commits, report:
- The `beacon_list_conversion_actions` output (action names + IDs)
- The curl output from `/api/cairn/context` (scheduler block)
- The dry-run payload from Outcome 4
- All commit SHAs
- Any errors or surprises

Push all commits.
