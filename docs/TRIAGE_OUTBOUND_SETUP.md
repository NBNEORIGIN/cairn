# Triage Phase B — Outbound Sent-folder capture setup

One-off ops step to enable Phase B of the thread-association
feature. Without this, the Sent-folder cron runs every 15 min
and exits cleanly with `status='missing_credentials'` — no harm,
no coverage.

## What this unlocks

- Every email you send from `toby@nbnesigns.com` gets ingested
  into `cairn_email_raw` with `direction='outbound'`
- If that email continues a thread already associated with a CRM
  project, the association's `last_message_at` + `message_count`
  are bumped — the CRM has full conversation history
- Deek's memory surfaces your replies the same way it surfaces
  client messages — so next time you ask "what did I say to
  Julie about lead time?", the answer is there

## The step

Set `IMAP_PASSWORD_TOBY` on the Deek host, using your IONOS
toby@ mailbox password (or an app-specific password if you've
enabled them):

```bash
ssh root@178.104.1.152
sudo -e /opt/nbne/deek/deploy/.env
# add at bottom:
IMAP_PASSWORD_TOBY=<your toby@ IMAP password>

cd /opt/nbne/deek/deploy && ./build-deek-api.sh deploy
```

The `deploy` flag rebuilds + restarts so the container picks up
the new env var.

## Verify

Manually trigger one poll:

```bash
docker exec -w /app -e PYTHONPATH=/app deploy-deek-api-1 \
  python scripts/process_sent_folder.py --verbose
```

Expected output:

```
INFO  result: {'ingested': <N>, 'already_seen': 0,
               'associations_touched': 0, 'errors': 0,
               'folder': 'Sent', 'status': 'ok'}
```

First run ingests up to 50 of your most recent sent messages.
Subsequent runs only pick up new ones (dedup on message_id).

## Check it's working over time

```sql
SELECT direction, COUNT(*)
  FROM cairn_email_raw
 WHERE created_at > NOW() - INTERVAL '24 hours'
 GROUP BY direction;
```

After a day of use, expect outbound count to be similar to the
number of replies you've sent from toby@.

## Compliance note

This polls YOUR mail, not anyone else's. The data is stored on
the Deek instance (Hetzner) under your control. Nothing is
shared with third parties. If you ever want to disable it:

1. `unset IMAP_PASSWORD_TOBY` in `.env`
2. `./build-deek-api.sh deploy` — cron resumes, sees no creds,
   logs `status='missing_credentials'`, does nothing
3. (Optional) drop already-ingested outbound with:
   ```sql
   DELETE FROM cairn_email_raw WHERE direction = 'outbound';
   ```

## Troubleshooting

**`authentication failed`** — wrong password. IONOS doesn't
like bare account passwords for IMAP if 2FA is on; generate an
app-specific password in the IONOS control panel and use that.

**`no Sent folder`** — the folder isn't named what we expect.
The code tries `Sent`, `INBOX.Sent`, `Sent Items`,
`Sent Messages`, `[Gmail]/Sent Mail`. If your IONOS setup uses
something else, check the log for the actual folder list:

```bash
# in the deek-api container:
python -c "
from core.email_ingest.imap_client import connect_imap
c = connect_imap('toby')
print(c.list())"
```

Add the correct folder name to `SENT_FOLDER_CANDIDATES` in
`core/email_ingest/sent_folder.py` as a follow-up PR.
