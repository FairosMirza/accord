# Single sign-on with Microsoft Entra ID

Accord has no passwords of its own. In production people sign in with their Orvane Microsoft 365 account using OpenID Connect (authorization code flow with PKCE). This is the one-off setup for Orvane IT, about 15 minutes.

## 1. Register the application

In the Entra admin centre go to **Applications → App registrations → New registration**:

- **Name:** Accord
- **Supported account types:** Accounts in this organizational directory only (single tenant)
- **Redirect URI:** Web, `https://<accord-host>/api/auth/callback`

Then, on the new registration:

1. **Certificates & secrets → New client secret.** Put the value in Secret Manager (below), never in code or chat.
2. **Token configuration → Add optional claim → ID token:** `email`. Accord falls back to `preferred_username` if it's missing.
3. **API permissions:** the defaults (`openid`, `profile`, `email`) are enough. Grant admin consent so nobody sees a consent prompt.
4. Optionally, under **Enterprise applications → Accord → Properties**, set **Assignment required = Yes** and assign the "All employees" group. That limits who can sign in.

Write down the **Directory (tenant) ID** and the **Application (client) ID**.

## 2. Configure Accord

```bash
printf '%s' '<client secret>' | gcloud secrets create accord-oidc-client-secret --data-file=- --project <project>
gcloud secrets add-iam-policy-binding accord-oidc-client-secret --project <project> \
  --member serviceAccount:accord-run@<project>.iam.gserviceaccount.com --role roles/secretmanager.secretAccessor

gcloud run services update accord --region europe-west3 --project <project> \
  --update-env-vars ACCORD_OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0,ACCORD_OIDC_CLIENT_ID=<client-id>,ACCORD_ALLOWED_EMAIL_DOMAINS='["orvane.com"]' \
  --update-secrets ACCORD_OIDC_CLIENT_SECRET=accord-oidc-client-secret:latest
```

For production, also set `ACCORD_ENVIRONMENT=production` and `ACCORD_DEMO_MODE=false`. Accord refuses to start in production with demo mode on.

## How people are matched

1. Accord matches on the Entra object ID (`oid`), then on email for a person's first sign-in.
2. With `ACCORD_OIDC_JIT_PROVISIONING=true` (the default), someone who isn't in Accord yet is added as an employee on first sign-in. An administrator then sets their manager. With the directory sync (a next step), managers and departments come from Entra automatically.
3. Deactivated people can't sign in, and their sessions are revoked.

## Notes

- Sessions last 12 hours (`ACCORD_SESSION_TTL_HOURS`). Entra's own sign-in policies (MFA, conditional access, device compliance) apply before Accord ever sees the user.
- The sign-in redirect uses state, nonce and PKCE. ID tokens are validated against Entra's published keys, issuer and audience.
