# Company access and authenticator rollout

The public landing page is `/`. It exposes branding and login/onboarding actions only. Anonymous dashboard APIs, exports and data-bearing static assets stay closed. Microsoft or Google verifies an identity but does **not** create a dashboard session. Approved accounts must create a password and confirm a TOTP authenticator.

## Configuration

Keep the existing Microsoft client ID, client secret and exact callback origin. Verified Microsoft work/personal accounts and verified Google accounts may request access, regardless of email domain. Google requires the separate configuration described below. Every request is bound to the validated issuer and subject; only explicit owner approval grants access. A matching email never links identities or inherits approval.

Set a separate `AUTH_MFA_ENCRYPTION_KEY`, generated with `cryptography.fernet.Fernet.generate_key()`. `scripts/configure_company_auth.py` creates this key in the ignored local `.env` without printing it. On the VM, use a root-only environment file and persistent storage. Keep a private backup of the key; losing or replacing it prevents decryption of existing authenticator seeds. Do not put either this key or the Microsoft client secret in chat, screenshots, source control or browser JavaScript.

All password/MFA access fails closed without a valid encryption key. Enrol the owner before approving other accounts.

## Owner first

1. On startup, SQLite's backup API saves a `.pre-company-*.bak` database backup before migration. Protect this backup exactly like the live database. Legacy sessions and in-progress Microsoft flows are invalidated. The owner identity remains approved.
2. The owner visits **Check request status / account setup**, verifies the same Microsoft identity, creates a 15–128 character dashboard password and scans the private QR code with a phone authenticator.
3. Enter its six-digit code. The current deployed version still displays ten single-use recovery codes; the planned code-free enrolment requires the email sender to be live and separately verified before removing that fallback. The QR is served only to the freshly verified approved identity.
4. Open **Access requests** from the signed-in account controls. Review a request's verified issuer/subject, name, reason and submission time. Approve/reject and choose Hidden/View/Edit for every section. New requests have no grants. No mail is sent.
5. An approved user returns through the same Microsoft or Google verification to complete password/MFA setup. Later logins use email + password + authenticator (or one unused legacy recovery code). Owner cannot be demoted, revoked or permission-reduced in the app.

## Reset and revocation

Where Microsoft 365 mail is configured, password reset uses a short-lived link sent to the approved email address and a valid authenticator code. It invalidates existing sessions. The older fresh-identity-verification reset remains available as a fallback during mail rollout; it accepts the authenticator or an unused legacy recovery code. If the phone is lost, the verified user requests a lost-factor reset; the owner reviews it in Access requests. Approval clears factors and password, invalidates sessions/verifications, and requires fresh verification of the same identity plus complete setup again. It does not change approval or grants.

Owner lost-factor recovery is a server-administrator procedure: use `scripts/recover_owner_factor.py` with the persistent database path, exact owner issuer and subject, and an explicit confirmation. It creates a backup, audits the reset, clears the owner's factors and sessions, and requires the same Microsoft identity to complete setup. It cannot create a different administrator or grant a company user access. Do not use it as routine login.

Sessions use opaque cookies, eight-hour absolute expiry and thirty-minute inactivity expiry. HTTPS cookies are Secure, HttpOnly and SameSite=Lax. Mutation/forced-refresh CSRF checks remain mandatory. TOTP accepts the current interval plus one interval of clock drift; consumed counters cannot be replayed. Account/IP attempt limits persist in SQLite. Permission changes and revocation remove sessions; authenticated WebSocket guards terminate revoked/expired connections within five seconds.

## Section enforcement

`section_permissions.py` contains the route/metric policy. Hidden data is neither requested by the client nor served by the backend. View allows calculations and exports; Edit additionally permits the section's supported uploads, imports and source refreshes. The owner alone manages access. `/api/trackers` filters its catalogue, and `/api/selectors/ports` returns only stable ID, name, country and coordinates to sections requiring a port picker. The India coal panel inside voyage analysis requires both relevant section grants.

Unclassified endpoints, the retired data hub, generic uploads without section ownership, user datasets without classified ownership, arbitrary static data and API schema documentation are denied, including to the owner. Explicit automation refresh endpoints retain their server token path; a token grants no browser/dashboard access. Background weather and AIS collection is independent of user sessions.

## Deployment acceptance

Before enabling Google requests and recovery mail on Azure, verify one real Gmail requester, the owner review, a viewer and a limited editor, plus delivery to an approved mailbox and the complete reset. Real credentials and authenticator codes must be entered by those people. Local tests use synthetic accounts and temporary databases, with no invitation emails or directory changes.

Deploy code and dependencies with the existing package script; it excludes `.env`, uploads and private database/key files. Configure the MFA key privately on the VM before restart. Keep the SQLite backup and encryption-key backup for rollback; reverting old Microsoft-only code would remove the new MFA requirement, so rollback must be an intentional owner action. Do not promote staged or fake test accounts to production.

Security references: [OWASP MFA recovery](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html), [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [Microsoft signed identity claims](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference).

## Google / Gmail access requests and Microsoft 365 recovery mail

The landing page can now offer **Request access with Google / Gmail**. Google verification uses an authorization-code flow with state, nonce and PKCE. The signed ID token must have the configured audience, Google's issuer, a valid expiry, and `email_verified=true`. An account is keyed by issuer and subject; a Google identity never inherits permissions from a Microsoft identity with the same email label. Verification only permits submitting an access request. The owner must still approve the exact identity and assign section grants; the user then sets up a password and TOTP authenticator. This is not Google API or Gmail mailbox access.

To enable it, create a Google Cloud OAuth **Web application** client and configure its consent screen for external users. Add exact authorized redirect URIs for the origins you use, for example `http://localhost:8000/auth/google/callback` and `https://howe-robinson-dashboard.centralindia.cloudapp.azure.com/auth/google/callback`. Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to the server's private environment, then restart. Keep the client secret out of source control and browser code. Without both values, the Google request action remains unavailable. Google may initially restrict an OAuth app in testing mode to its listed test users; finish Google's publishing requirements before inviting other Gmail accounts. [Google's web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server) and [ID-token validation guide](https://developers.google.com/identity/openid-connect/openid-connect) describe these controls.

Approved users can request a password-reset email from the login page. The link lasts 15 minutes, is single-use, and contains its token only in the URL fragment so the token is not sent in a page request or web-server access log. Completing the reset requires the enrolled six-digit authenticator code; a recovery code cannot replace it in this flow. Approval and credential version are rechecked under a database write lock, then all old sessions are invalidated. Unknown addresses receive the same acknowledgment. If the authenticator is lost, the existing owner-approved lost-factor procedure remains separate. The older identity-verification reset route remains available while the mail sender is being configured.

The initial sender is the owner's personal `dynasty9939@outlook.com` mailbox. `MAIL_PERSONAL_SENDER` selects delegated Microsoft Graph `Mail.Send`. The owner must connect the same Microsoft identity from Access requests after the exact `/auth/mail/callback` redirects are registered. The refresh token is encrypted in persistent access storage; email reset stays disabled until this connection succeeds. This personal account does not use Exchange application RBAC. A future Microsoft 365 work-mail sender can instead use a separate app registration with `MS365_MAIL_*` environment values and mailbox-scoped Exchange application RBAC. See [the setup guide](google-m365-setup.md), [Microsoft Graph sendMail](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0), and [Exchange application RBAC](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac).
