# Operations

## Environments

| | Demo (running now) | Production (when Orvane says go) |
| --- | --- | --- |
| URL | https://accord-479375989955.europe-west3.run.app | Custom domain, e.g. accord.orvane.com |
| Sign-in | Demo personas (`ACCORD_DEMO_MODE=true`) | Entra ID SSO only ([SSO.md](SSO.md)) |
| Data | Generated demo company, resettable | Real, never reset |
| Email | Stored in the outbox, not sent | SMTP relay or Microsoft Graph via a shared mailbox |

## Configuration

All configuration is environment variables prefixed `ACCORD_` ([backend/app/config.py](../backend/app/config.py)). Secrets come from Secret Manager:

| Secret | Purpose |
| --- | --- |
| `accord-database-url` | Postgres connection (TLS required) |
| `accord-session-secret` | Key for hashing session tokens and signing the SSO handshake |
| `accord-job-token` | Shared secret Cloud Scheduler sends to `/internal/jobs/reminders` |
| `accord-oidc-client-secret` | Entra ID client secret (production) |

Rotating a secret means adding a new version and redeploying. Rotating the session secret signs everyone out.

## Deploying and rolling back

- **Deploy:** push to `main`. GitHub Actions tests, builds `europe-west3-docker.pkg.dev/<project>/accord/accord:<sha>`, deploys and smoke-tests. Database migrations (Alembic) run on start-up, one instance at a time under a Postgres advisory lock. They are written to be additive, so the previous revision keeps working against the new schema.
- **Roll back:** `gcloud run services update-traffic accord --region europe-west3 --to-revisions <previous-revision>=100`, or redeploy an older image tag.

## Scheduled jobs (Cloud Scheduler)

| Job | When | What |
| --- | --- | --- |
| `accord-reminders` | Hourly, 08:00–18:00 Dubai, Monday to Friday | Reminds approvers after 24 hours, flags contracts coming up for renewal, sends queued email |
| `accord-warm` | Every 10 minutes, 07:00–21:00 Dubai | Keeps one instance warm so the first page load is quick |

## Data, backups and retention

- **Database:** Neon Postgres in Frankfurt (eu-central-1). Point-in-time restore is within Neon's retention window (short on the free plan). For production: a paid plan with 7–30 days of history, plus a nightly `pg_dump` to a locked Cloud Storage bucket.
- **Documents:** a private Cloud Storage bucket with uniform access, public access prevention and object versioning. The app's service account can create and read objects but not delete them.
- **Audit log:** append-only (a database trigger blocks UPDATE, DELETE and TRUNCATE) and hash-chained. **Audit log → Verify integrity** re-computes the chain.
- **Retention:** submitted requests are never deleted, only withdrawn, cancelled or closed. Production should keep financial records for at least five years (UAE requirement). To be confirmed with Finance and Legal for each site's country.
- **Residency:** everything is in Frankfurt (EU). If Orvane needs data in the UAE, Google Cloud's Doha region or Azure UAE North would host the same container.

## Monitoring

- Logs are structured JSON on stdout (Cloud Logging), one line per request with method, path, status, duration and request ID. Unhandled errors include a stack trace and show up in Error Reporting.
- Suggested alerts: uptime check on `/api/health` (or `/api/ready`, which touches the database), 5xx rate, and failed scheduler runs.

## Common tasks

| Task | How |
| --- | --- |
| Someone joins | They sign in with SSO and are added. An admin sets their manager under **People** |
| Someone leaves | **People → Leaver**. Sign-in is blocked, and pending approvals and direct reports move to their manager |
| The COO changes | Give the new person the COO position under **People**. The rules follow the position |
| New approval limits | Tom edits **Approval rules**, tries them out, and publishes with a note |
| An approver is stuck or away | They set cover, or an admin sets it for them |
| Demo reset | **Email outbox → Reset demo data** (demo mode only) |

## Costs

Everything runs inside free tiers today: Cloud Run's request-based free tier, Neon's free plan, and the free allowances for Cloud Storage, Secret Manager and Cloud Scheduler (3 jobs). A production setup with a paid Postgres plan, a custom domain and alerting would be roughly USD 30–60 a month at Orvane's size.
