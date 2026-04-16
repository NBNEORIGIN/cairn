# Beacon Phase 2 — Conversion pipeline wiring

Phase 1 is complete (D-008, scheduler verified). Phase 2 connects the
conversion actions created in Google Ads (D-009) to the existing Beacon
backend so that real form submissions produce uploadable conversions.

Read first:

- `projects/beacon/core.md` — decision log D-001 through D-009
- `wiki/modules/beacon.md` — current status and open housekeeping
- `docs/cairn/LOCAL_CONVENTIONS.md`

Standard Cairn protocol applies. Memory write-back with non-empty
`rejected`, `project="claw"`.

---

## Confirmed facts

- Beacon dev ports: 8017/3017
- Sub-account: `2028631064` (campaigns live here)
- MCC: `2141262231` (manager, never receives uploads)
- Three conversion actions exist in Google Ads (created 2026-04-15):
  1. `NBNE Signs — Contact Form` — offline import, qualified lead
  2. `Phloe — Contact Form` — offline import, qualified lead
  3. `NBNE — Phone Call Lead` — website call tracking (tag-based, not API-uploaded)
- `google-ads` pinned at 30.0.0 (API v20)
- Redis broker: use `tporadowski/redis` portable at
  `C:\Users\zentu\tools\redis-win\redis-server.exe` (Docker Desktop is
  broken, D-008 documents why)

## Existing code (already built in Phase 1)

The following are ALREADY IMPLEMENTED. Do not rebuild them. Read them,
understand them, wire into them:

- `attribution/views.py` — `POST /api/capture/` (gclid capture from
  beacon.js, Origin-matched to tenant), `POST /api/capture/<id>/attach/`
  (link external_ref to capture)
- `webhooks/views.py` — `POST /api/webhooks/conversion/` (HMAC-signed
  inbound webhook from Phloe/CRM/Manufacture, creates `Conversion` row,
  resolves gclid via `capture_id` or `gclid` field, checks 90-day window)
- `attribution/models.py` — `GclidCapture`, `Conversion` (with
  `UploadStatus`, `SourceModule`), `ConversionUploadJob`
- `ads/client.py` — `BeaconAdsClient.upload_click_conversions()` (builds
  `ClickConversion` protobuf, calls `ConversionUploadService`, handles
  partial failure)
- `attribution/management/commands/beacon_upload_conversions.py` — the
  scheduled upload command. Groups pending conversions by account, batches
  per 2000, `SELECT FOR UPDATE SKIP LOCKED`, retry up to 5 attempts.
  **Note line 125:** `conversion_action_id` is currently set to
  `conv.conversion_name` with a `# Phase 2` comment. This is where real
  action IDs need to be resolved.
- `tenants/models.py` — `BeaconTenant` with `allowed_origins` JSON field
  (used by capture endpoint for CORS-style Origin matching)

## The work — 5 outcomes, each as an atomic commit

### Outcome 1 — Pull and store conversion action resource names

Write a management command `beacon_list_conversion_actions` that calls
`ConversionActionService` via the google-ads library to list all
conversion actions for sub-account `2028631064`. Print the resource name,
name, category, and status for each.

Then add a `conversion_action_map` JSONField to `BeaconTenant` (or a new
`ConversionActionConfig` model — your call on which is cleaner). This
maps a logical conversion name (e.g. `"NBNE Signs — Contact Form"`) to
the Google Ads resource name
(`customers/2028631064/conversionActions/NNNNNNNN`).

Update `beacon_upload_conversions.py` line 125 so it resolves
`conv.conversion_name` through this map instead of passing it raw.

Run the new command against the live sub-account to verify the three
actions from D-009 are visible. Paste the output in the commit message.

Commit: `feat(beacon): pull conversion action resource names and wire upload pipeline`

### Outcome 2 — Fix the `/api/cairn/context` auth bug

The `cairn_app.views.context_endpoint` view is unreachable from HTTP
because DRF's global `JWTAuthentication` rejects the custom
`Bearer <CAIRN_API_KEY>` header (see D-008). Fix by adding
`@authentication_classes([])` to the view (or writing a proper
`CairnKeyAuthentication` class that returns `AnonymousUser` on valid key
and raises on invalid key — your call).

Verify with:
```
curl -s -H "Authorization: Bearer <CAIRN_API_KEY>" http://localhost:8017/api/cairn/context
```

Must return the full context JSON, not a 401.

Commit: `fix(beacon): bypass jwt auth on cairn context endpoint`

### Outcome 3 — beacon.js snippet for gclid capture

Write a small JS snippet (`beacon.js`, <50 lines) that:
1. On page load, reads `gclid` from the URL query string
2. Stores it in `localStorage` with a 90-day expiry timestamp
3. On form submission (configurable selector, default `form`), sends
   `POST /api/capture/` with the stored gclid, `landing_url`, and
   `referrer`
4. Stores the returned `capture_id` in a hidden form field or
   `localStorage` so the downstream system (Phloe/nbnesigns contact
   form) can pass it with the lead record

The snippet must be embeddable on both nbnesigns.co.uk and phloe.co.uk
tenant pages. It talks to Beacon's API, not to Google directly.

Place it at `backend/static/beacon.js` so it can be served by Django's
static files (or a CDN later). Include a brief HTML comment at the top
showing the embed tag:

```html
<!-- Beacon GCLID capture -->
<script src="https://beacon.nbnesigns.co.uk/static/beacon.js"
        data-beacon-api="https://beacon.nbnesigns.co.uk/api"
        async></script>
```

Do NOT install it on any live site in this session. Just build and test
the snippet.

Commit: `feat(beacon): beacon.js gclid capture snippet`

### Outcome 4 — Google global site tag for nbnesigns.co.uk

The Google tag is needed for Action 3 (phone call forwarding). This
outcome is documentation + a management command, NOT a live deploy.

Write a management command `beacon_show_gtag --customer-id 2028631064`
that:
1. Fetches the Google Ads tag snippet for the account via the API (or
   constructs it from the known conversion ID + customer ID if the API
   doesn't provide a ready-made snippet)
2. Prints the `<script>` block that needs to be added to the `<head>` of
   nbnesigns.co.uk
3. Prints the phone number replacement snippet that goes before `</body>`

Add a section to `projects/beacon/core.md` under a new heading
`## Google Tag Installation` with the exact instructions for installing
the tag on nbnesigns.co.uk (which repo, which file, where in the HTML).

Do NOT modify nbnesigns.co.uk in this session.

Commit: `docs(beacon): google tag installation instructions for nbnesigns.co.uk`

### Outcome 5 — End-to-end dry run

Write a management command `beacon_dry_run_conversion` that simulates the
full pipeline without hitting Google Ads:

1. Creates a `GclidCapture` row with a fake gclid
2. Creates a `Conversion` row linked to it, with `conversion_name` set
   to one of the real action names from Outcome 1
3. Runs `beacon_upload_conversions` in `--dry-run` mode (add the flag if
   it doesn't exist) that resolves the conversion action, builds the
   upload payload, logs it, but does NOT call the API
4. Prints the payload that WOULD have been sent
5. Cleans up the test rows

This proves the full path from gclid → conversion → upload payload
without side effects.

Commit: `feat(beacon): dry-run conversion pipeline for verification`

---

## What NOT to do

- Do not deploy Beacon to Hetzner. Dev-only for now.
- Do not install beacon.js or the Google tag on any live website.
- Do not modify nbnesigns.co.uk or any Phloe tenant site.
- Do not create new conversion actions in Google Ads — the three from
  D-009 are sufficient.
- Do not change the Celery schedule or job cadence.
- Do not refactor the existing upload command beyond wiring the action ID
  resolution — the retry/batch logic is tested and correct.

## Status report

After all 5 commits, report:
- All 5 commit SHAs
- The output of `beacon_list_conversion_actions` (the three action names
  and resource names)
- The curl output from the fixed `/api/cairn/context` endpoint (scheduler
  block only)
- The dry-run payload from Outcome 5
- Any errors or surprises encountered

Push all commits.
