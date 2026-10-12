# Microsoft sign-in and approved users

Authentication is enabled by default, including localhost. Render and
`APP_ENV=production` always require it. A missing registration, failed database
or absent mounted Render disk never exposes dashboard data.

## Register Microsoft sign-in

1. Open Microsoft Entra admin center → App registrations → New registration.
   Name it **Howe Robinson Dashboard**. Select **Accounts in any organizational
   directory and personal Microsoft accounts**.
2. Add **Web** redirect URIs:
   - `http://localhost:8000/auth/callback`
   - `https://hrp-dashboard-6xtk.onrender.com/auth/callback`
   Add a different local port or custom domain only when that origin is used.
   Use the exact registered origin; do not alternate localhost and 127.0.0.1.
   The portal accepts HTTP localhost directly. HTTP 127.0.0.1 requires a
   manifest edit; use localhost for this portal-based setup.
3. Copy the Application (client) ID. Under Certificates & secrets, create a client
   secret and save its **value** in server environment configuration. Do not put
   it in source control, browser JavaScript, screenshots or chat.
4. Configure `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` and `AUTH_BASE_URL`
   (`http://localhost:8000` locally; the HTTPS origin on Render). No Microsoft
   Graph or mail permissions are needed. The app requests `openid profile email`.
5. Restart the server and use `/auth/login`. Work-account consent restrictions
   may require the user's organization administrator to permit the application.

References: [Microsoft app registration](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app),
[supported account types](https://learn.microsoft.com/en-us/entra/identity-platform/v2-supported-account-types),
[email claim limitations](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims-reference),
[Authlib OAuth clients](https://docs.authlib.org/en/stable/oauth2/client/http/index.html).

## Bootstrap the owner

1. With Microsoft credentials configured, sign in using **your own** Microsoft
   account. You initially see Account not approved, with Issuer and Subject.
   These identifiers are obtained only after validated Microsoft sign-in.
2. Copy those exact values to `AUTH_ADMIN_ISSUER` and `AUTH_ADMIN_SUBJECT` in the
   server environment. Check that the identifiers belong to your account.
3. Restart. This one-time, identity-bound bootstrap grants your previously
   verified account administrator access; an active session can continue.
   Sign in again if your session has expired. The database records that bootstrap
   is consumed.
4. Remove the bootstrap variables after success. Changing them later cannot
   silently promote another account. Never delete the database to reset access.
   Back it up before deployment or storage changes.

## Approve and revoke users

Open **Manage access** beside your signed-in account. Add the exact email label.
Ask the person to sign in and share their Issuer and Subject through a trusted
channel. Compare those identifiers against their request before approving it.
Emails are mutable labels, not proof of identity: an invitation alone never
grants access, and a different account with the same label never inherits access.

Approve the specific identity as Viewer by default. Viewers can browse, search,
calculate routes, analyze retained/uploaded datasets and export. Shared source
uploads, refreshes, report downloads into the shared archive, API connections,
relationships and access management require Administrator. Approval or role
changes invalidate existing sessions; the person signs in again. Revocation
invalidates all sessions immediately. Invitation disabling alone does not revoke
an already approved identity. The last active administrator cannot be demoted
or revoked.

Sessions expire after eight hours or thirty minutes without requests. Cookies
are HttpOnly/SameSite=Lax and Secure on HTTPS. Logout is CSRF-protected and deletes
the session. No provider access or refresh tokens are retained. Authentication
flow state, nonce and PKCE verifier are transient and single use (ten minutes).
The callback never uses caller-supplied return URLs.

## Storage, hosting and rollout

The database is `HRP_STORAGE_DIR/_access/access.sqlite3`, separate from AIS and
other data. Back up this directory using SQLite's backup API or while the
service is stopped; retain it through redeployments. Keep one application worker
on one service instance for this SQLite deployment.

The existing `render.yaml` uses Free compute and does **not** declare a disk.
Render Free web services cannot attach persistent disks. `render-auth.yaml` is
an **opt-in paid deployment template**, with Starter compute and a 1 GB disk
mounted at `/var/data/hrp`; no hosting plan is changed by this code. For the
existing service, configure the paid instance/disk and environment variables
in its dashboard instead of accidentally creating a second service. Preserve
existing service secrets and migrate any needed old data before cutover.
The runtime checks that `HRP_STORAGE_DIR` really is a mount on Render, not merely
a directory. It fails closed otherwise. [Render disks](https://render.com/docs/disks),
[Free-service limitations](https://render.com/docs/free).

Deployment sequence: configure disk and registration → deploy → verify public
health/login and blocked unauthenticated APIs → bootstrap owner → approve a
test viewer → verify browsing/export and rejected uploads/refreshes → approve
real users. Rotate expiring client secrets before they lapse. Review recent
login and permission events in the Access panel. Do not roll back to a build
without access control on an exposed service; restore a verified backup when
recovering storage. Background AIS/weather tasks continue without user login.

## API and automation

- `GET /api/auth/me`: authenticated account, approval status and session CSRF
  token; no-store. Pending users see only their own identity, not dashboard data.
- `GET /api/admin/access`: accounts, invitations and last 100 access audit events.
- `POST /api/admin/access/invitations`: `{email, active}`.
- `POST /api/admin/access/accounts/{id}`: `{status: approved|revoked, role: viewer|admin}`.
- `POST /auth/logout`: revoke current session.

Browser mutations require `X-CSRF-Token`, including a forced NPP GET refresh.
The browser fetch wrapper adds it only for same-origin requests. Cross-origin
requests and authentication callback URLs never carry this token.

`APP_ADMIN_TOKEN` remains accepted only for the explicit source-refresh endpoints
listed in `AUTOMATION_POSTS`, with no browser Origin or session cookie. It cannot
open the dashboard, download data, manage access or upload sources. It is not a
replacement for Microsoft login. Public `/api/health` exposes liveness only.

For isolated automated tests or explicitly opted-out local development, set
`APP_AUTH_ENABLED=false`. This never disables production authentication and is
limited to loopback requests (or TestClient); do not use it for deployment.
There is no test-login endpoint, fake production identity or password fallback.
