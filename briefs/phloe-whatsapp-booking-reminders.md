# Phloe Brief — WhatsApp booking reminders (GDPR-compliant)

**Target repo:** Phloe (`D:\phloe` or equivalent / `NBNEORIGIN/phloe-*`)
**Module:** Phloe core (booking system)
**Consumer:** Claude Code (Phloe session)
**Protocol:** Follow `NBNE_PROTOCOL.md` and Phloe's local CLAUDE.md.
**Origin:** Deek session 2026-04-22 — Toby scoped this as a
follow-up to the Deek Telegram nudges feature. Deek's own nudges
ship separately over Telegram; this brief is specifically about
client-facing booking reminders via WhatsApp.

---

## Why this brief exists

Phloe currently sends booking confirmations + 24h-before reminders
via email (Postmark). Clients often miss emails. A WhatsApp
reminder lands in the same thread they use for their daily life
and gets a 95%+ read rate within an hour.

**This is NOT a marketing channel.** It's a transactional
appointment-reminder channel under strict opt-in + template rules.
Conflating the two would get the WhatsApp Business number
suspended and breach GDPR.

---

## Pre-flight self-check

1. Confirm Phloe's current booking model and how reminder emails
   are sent today (which Postmark template + when the cron fires).
2. Confirm which Phloe tenants would turn this on — DemNurse +
   Amble Pin Cushion + Ganbarukai + NAPCO Pizza are live; others
   may or may not want WhatsApp.
3. Confirm Phloe's current consent model — how are
   marketing-email opt-ins captured today? WhatsApp consent must
   be SEPARATE, not a subset.
4. Report findings before Task 1.

---

## Tasks

### Task 1 — WhatsApp Business Cloud account setup

**Ops / manual work** (Toby does this, Phloe engineers consume it):

- Create a Meta Developer account if one doesn't exist for NBNE
- Register the WhatsApp Business Cloud API application
- Verify the business (takes 1-3 days; Meta wants company docs)
- Register a phone number (per-tenant? or one Phloe-wide number?
  — see Task 5)
- Submit the `appointment_reminder` template for approval (see Task 3)

**Deliverable for Phloe engineering**: Meta App ID, App Secret,
Phone Number ID, Access Token (long-lived). Provided as
environment variables:

```
WHATSAPP_APP_ID=...
WHATSAPP_APP_SECRET=...
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_VERIFY_TOKEN=...   # for webhook verification
```

### Task 2 — Prisma schema additions

Add three new models. Migration name
`YYYY_MM_DD_whatsapp_reminders`.

```prisma
model WhatsAppConsent {
  id            String   @id @default(cuid())
  tenantId      String   @map("tenant_id")     // per-tenant scoping
  tenant        Tenant   @relation(fields: [tenantId], references: [id])
  clientId      String?  @map("client_id")     // nullable if guest booking
  client        Client?  @relation(fields: [clientId], references: [id])
  phoneNumber   String   @map("phone_number")   // E.164 format
  grantedAt     DateTime @map("granted_at")
  grantSource   String   @map("grant_source")   // e.g. 'booking-form'
  grantIp       String?  @map("grant_ip")       // audit trail
  revokedAt     DateTime? @map("revoked_at")
  revokedVia    String?   @map("revoked_via")   // 'stop-reply' | 'admin' | 'gdpr-request'

  @@index([tenantId, phoneNumber])
  @@index([phoneNumber, revokedAt])
  @@map("whatsapp_consent")
}

model WhatsAppMessage {
  id              String   @id @default(cuid())
  tenantId        String   @map("tenant_id")
  direction       WAMessageDirection
  phoneNumber     String   @map("phone_number")
  messageSid      String?  @unique @map("message_sid")   // Meta's wa_id
  templateName    String?  @map("template_name")          // e.g. 'appointment_reminder'
  templateParams  Json?    @map("template_params")
  body            String?  @db.Text                       // plaintext for freeform messages
  status          WAMessageStatus @default(queued)
  statusUpdatedAt DateTime @default(now()) @map("status_updated_at")
  relatedBookingId String? @map("related_booking_id")
  relatedBooking  Booking? @relation(fields: [relatedBookingId], references: [id])
  errorCode       String?  @map("error_code")
  errorDetail     String?  @db.Text @map("error_detail")
  createdAt       DateTime @default(now()) @map("created_at")

  @@index([tenantId, createdAt])
  @@index([relatedBookingId])
  @@index([phoneNumber, createdAt])
  @@map("whatsapp_messages")
}

enum WAMessageDirection { inbound outbound }
enum WAMessageStatus { queued sent delivered read failed revoked }

model WhatsAppReminderSchedule {
  id             String   @id @default(cuid())
  tenantId       String   @map("tenant_id")
  bookingId      String   @unique @map("booking_id")
  booking        Booking  @relation(fields: [bookingId], references: [id])
  scheduledFor   DateTime @map("scheduled_for")   // e.g. 24h before booking
  sentAt         DateTime? @map("sent_at")
  skippedAt      DateTime? @map("skipped_at")
  skipReason     String?  @map("skip_reason")     // 'no-consent' | 'opted-out' | 'booking-cancelled'

  @@index([scheduledFor, sentAt])
  @@map("whatsapp_reminder_schedules")
}
```

Add `Booking.whatsappReminderSchedule` back-reference and a
`whatsappConsentAtBooking: Boolean` column (snapshot — whether
consent was given at time of booking, for audit).

### Task 3 — Approved WhatsApp templates

Submit to Meta via the Business Cloud console:

**Template: `appointment_reminder_en`**
```
Hi {{1}}, just a reminder that you have a {{2}} appointment
booked for {{3}}. Reply STOP to unsubscribe.
```

Parameters: {client_name, service_name, date_time_string}

Category: `UTILITY` (not MARKETING — critical for compliance).

Approval takes ~24h. If rejected, iterate wording; keep it
plain-factual, no promotional tone.

### Task 4 — Opt-in capture at booking

On the booking form:

```
☐ Send me a WhatsApp reminder 24 hours before my appointment
  (optional; we'll only message you about this booking)
```

- Default UNCHECKED
- Placed AFTER the email field, with helper text clarifying:
  "We use this for reminders only — never marketing."
- Phone number captured (already captured today?) must be E.164
- On submit: if checked, write a `WhatsAppConsent` row with
  `grantedAt`, `grantSource='booking-form'`, `grantIp` from
  request.

If the same phone number has `revokedAt` set in this tenant, the
checkbox should be greyed out with "You've previously unsubscribed
— to re-enable, please contact the business directly."

### Task 5 — Phone-number architecture decision

Two options — Phloe session must pick one before Task 6:

**(a) One Phloe-wide WhatsApp number**
- Cheaper (one Meta verification, one monthly fee)
- Messages sent "from Phloe on behalf of {business}" — template
  must include business name in the body
- Risk: one number means a WhatsApp policy violation on any
  tenant suspends reminders for ALL tenants

**(b) Per-tenant WhatsApp number**
- Each Phloe business gets their own verified number
- More expensive, more onboarding
- Better brand alignment — client sees "DemNurse" as sender, not
  "Phloe"
- Isolates policy risk

Recommend **(a) for v1** with explicit acceptance of the shared
risk, **(b) for Phloe Pro** (paid tier) as a differentiator.

### Task 6 — Scheduler + sender

Nightly (or hourly?) cron scans `WhatsAppReminderSchedule` for
rows with `scheduled_for < NOW() AND sent_at IS NULL AND skipped_at IS NULL`:

1. Load the booking + consent record
2. If `consent.revokedAt IS NOT NULL` → mark skipped with reason
3. If booking is cancelled → mark skipped
4. Else: POST to WhatsApp Cloud API with the template + params
5. Store the returned `wa_id` in `WhatsAppMessage.messageSid`
6. Set `sent_at` on the schedule row
7. On error: log `errorCode`, DON'T retry automatically (avoid
   spam loops) — alert admin

On booking creation: if consent given, insert a
`WhatsAppReminderSchedule` row with `scheduledFor = booking.startTime - 24h`.
On booking cancellation: set `skippedAt` on the schedule if not
yet sent.

### Task 7 — Inbound webhook + STOP handling

Endpoint: `POST /api/phloe/whatsapp/webhook`

Meta sends inbound messages + status updates here. Handler:

1. Verify the HMAC signature against `WHATSAPP_APP_SECRET`
2. Dispatch on `messages[].type`:
   - `text` with body "STOP" / "STOP ALL" / "UNSUBSCRIBE" / "OPT OUT"
     → set `WhatsAppConsent.revokedAt = NOW()`, `revokedVia = 'stop-reply'`
     → send acknowledgement: "You've been unsubscribed from
       {business} WhatsApp reminders. You won't receive any more
       messages from this number."
   - Any other text → currently no automated response (admin
     sees it in an inbox surface if one is built — future brief)
3. Log all inbound to `WhatsAppMessage` with `direction=inbound`

Status updates (delivered/read/failed) update the corresponding
outbound `WhatsAppMessage.status`.

### Task 8 — Admin surfaces

Minimum for v1:
- Per-booking: "WhatsApp reminder scheduled for YYYY-MM-DD HH:MM"
  (or "not scheduled — no consent")
- Per-client: "Opted in YYYY-MM-DD" or "Opted out YYYY-MM-DD"
- Admin panel page: WhatsApp messages log (sent / delivered /
  failed last 7 days)
- Admin action: "Manually resend reminder" button on individual
  bookings (audited to actor)

### Task 9 — Tests

- Unit: E.164 validation, consent check pipeline, STOP regex
- Unit: 24h-before schedule time calculation across DST transitions
- Integration:
  - Mock Meta API, submit reminder, verify status updates
  - Inbound webhook HMAC verification (valid + invalid sig)
  - STOP → revoke → subsequent send attempt is skipped
- Compliance:
  - New booking without opt-in → zero WA activity
  - Consent given → schedule exists → sent → status tracked
  - Cancellation → skipped, no send
  - GDPR deletion request → consent removed, messages anonymised
    (phone number hashed, body cleared)

### Task 10 — Retention + DPA update

- `WhatsAppConsent` rows retained until GDPR deletion request,
  even after revocation (demonstrability)
- `WhatsAppMessage.body` retained 90 days, then
  `body = NULL + phone_number = <hash>` — still enough for
  delivery statistics, no PII
- Update Phloe's Data Processing Addendum to list WhatsApp / Meta
  as a processor

### Deliverable

Single PR on Phloe repo with:
- Prisma migration
- Models + scheduler cron + webhook handler
- Opt-in UI + admin surfaces
- Tests green
- `docs/whatsapp-compliance.md` documenting the opt-in + opt-out
  flow + retention policy

---

## Out of scope

- **Marketing broadcasts.** Separate channel, separate opt-in,
  separate brief. Mixing them is a suspension risk.
- **Two-way conversational support.** Customer replies to
  reminders hit the webhook but aren't routed to any admin UI
  chat surface. A future brief can build that — requires a
  "Phloe inbox" concept.
- **Per-tenant number procurement** (Task 5 option b) — v2.
- **Analytics dashboards** beyond the simple per-tenant log.
- Integration with Deek's memory / intelligence surface — the
  Deek agent doesn't need to see these messages. If it ever
  does, that's a separate spanning brief with explicit GDPR
  review.

---

## Constraints

- Zero outbound messages without a valid `WhatsAppConsent` row
- Every send + skip logged for audit
- HMAC signature verification on every inbound webhook
- STOP reply must revoke within < 60 seconds
- Template approval via Meta — no freeform proactive messages
  outside the 24-hour customer service window
- No new cloud dependencies beyond Meta itself
- E.164 phone number validation mandatory — reject malformed
  numbers at booking time with a clear error

---

## Rules of engagement

Stay in the Phloe repo. Do NOT edit Deek (which is using
Telegram for its own nudges — independent channel). Do NOT expose
any WhatsApp data to Deek via new endpoints — the data lives in
Phloe's DB, period. If you want Deek to see message volumes,
write a separate spanning brief with an explicit GDPR / DPA
review.
