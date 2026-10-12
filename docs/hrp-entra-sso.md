# HRP Microsoft Entra SSO handoff and cutover

Prepared 1 October 2026. **The HRP SSO code is implemented locally but is disabled by default.** The current Azure login must remain available until HRP IT provisions its tenant application and an HRP administrator signs in successfully. This document supersedes the *existing personal-account app* advice in `azure-deployment.md` for the HRP cutover.

## Send this request to HRP IT

> Please register **Howe Robinson Dashboard** as a single-tenant Web application in the HRP Entra tenant. The production redirect URI is `https://howe-robinson-dashboard.centralindia.cloudapp.azure.com/auth/callback`. Please provide the tenant ID, application (client) ID, exact accepted HRP UPN/email domains, and your app-role assignment method. Set the Enterprise Application's **Assignment required** property to Yes. Configure the optional ID-token `acct` claim so the app can reject B2B guests (`acct=1`), and assign my HRP member account `HRP.Admin` before cutover. Please also assign one test viewer and one limited editor. I will give you the **public X.509 certificate** and SHA-256 thumbprint to upload under Certificates & secrets; the private key remains on the dashboard VM. Please configure a Conditional Access policy using your trusted corporate egress IPs/named locations so external sign-ins require Microsoft MFA. Please confirm licensing and test internal/external behavior with us.

There is **no password hash or user signing key to exchange**. HRP Entra authenticates users and publishes the ID-token verification keys. The dashboard certificate authenticates the web application to Entra at token exchange.

For localhost testing, IT should create a **separate development app registration** with `http://127.0.0.1:8000/auth/callback` (or the exact origin used), separate client ID and certificate. Do not add localhost to the production registration. No Microsoft Graph or mail permission is needed for dashboard sign-in.

## App roles for IT

Create user-assignable app roles with these exact `value` strings. Role display names can be descriptive. `HRP.Admin` grants all sections and emergency local-session revocation. For each section below, create both `HRP.<key>.View` and `HRP.<key>.Edit`. Edit includes View; no role means Hidden. Assign at least one role per user; do not use Default Access. Direct user assignment works without group-based assignment; IT should confirm its licence before relying on groups.

| Section | Key |
| --- | --- |
| Voyage & Tonne-Miles | `voyage_analysis` |
| AIS & Port Activity History | `port_activity` |
| Energy | `energy` |
| Ports | `ports` |
| India Coal | `india_coal` |
| Commodities | `commodities` |
| News & Intelligence | `news` |
| Live AIS | `live_ais` |
| Weather & Disruption Outlook | `weather` |
| Rivers, Reservoirs & Canals | `rivers` |
| Voyage Distance | `voyage_distance` |

IT owns role assignment and recovery. The dashboard does not approve requests, store dashboard passwords, send recovery codes or decide whether Microsoft Authenticator is required. The email entered on the page is only a login hint. The app validates the signed tenant, member claim, immutable `oid`, accepted UPN domain and app roles before issuing a dashboard session. A changed email label never links an old personal/Google account to an HRP identity.

## Certificate and configuration

On the production VM, create a persistent private directory accessible to the `hrp` service account. Run `scripts/prepare_hrp_sso_certificate.py` **as that account** with an absolute prefix such as `/var/lib/hrp/keys/dashboard-2026`. Give IT only `/var/lib/hrp/keys/dashboard-2026.cert.pem`, its printed SHA-256 thumbprint and expiry. Keep `/var/lib/hrp/keys/dashboard-2026.private.pem` mode 0400, owned by `hrp`; never email, upload to source control or include it in deployment archives. The package script excludes `.pem` and `.key` files. Back up the private key separately in an IT-approved secret store or plan a new certificate if the VM disk is lost. Begin rotation before expiry: add the new public certificate in Entra, update both VM paths, restart/test, then retire the old certificate.

Set these values in the root-managed `/etc/hrp/dashboard.env` only after IT confirms registration:

```text
HRP_SSO_ENABLED=true
HRP_ENTRA_TENANT_ID=<HRP tenant GUID>
HRP_ENTRA_CLIENT_ID=<HRP application GUID>
HRP_ENTRA_EMAIL_DOMAINS=<comma-separated confirmed HRP domains>
HRP_ENTRA_CERT_PATH=/var/lib/hrp/keys/dashboard-2026.cert.pem
HRP_ENTRA_PRIVATE_KEY_PATH=/var/lib/hrp/keys/dashboard-2026.private.pem
```

`AUTH_BASE_URL` remains the exact HTTPS dashboard origin. Missing or invalid HRP SSO configuration fails closed. Do not remove the old secrets or account database until cutover succeeds. After cutover, remove old personal Microsoft and Google login credentials from the service environment and disable their OAuth registrations as appropriate; retain the encrypted/SQLite historical access database backup under the existing retention policy.

## Acceptance and rollback

1. Back up live code, `/etc/hrp/dashboard.env`, the SQLite access database **using SQLite's backup API**, and the new certificate/key through approved secure storage. Deploy code with `HRP_SSO_ENABLED=false`; verify current login still works.
2. Provision the HRP registration, certificate, app roles and Conditional Access policy. Configure and enable HRP SSO on the VM. Confirm your assigned HRP member administrator can complete sign-in before the legacy path is retired.
3. Verify assigned viewer and editor permissions against UI, direct APIs, exports, uploads and streams. Verify unassigned HRP, guest, personal and Google users are denied. Confirm internal and external network challenges with IT; the app cannot configure or guarantee Conditional Access behavior.
4. Verify role removal and network change force a new Entra sign-in within 15 minutes, and test emergency session revocation. Confirm session inactivity (30 minutes) and maximum lifetime (8 hours). An existing session can remain usable for up to 15 minutes after an IT assignment change; operationally urgent revocation requires the administrator to revoke its local sessions.
5. If acceptance fails, restore the previous code and environment configuration from the same backup, restore the SQLite snapshot only if required, and restart the service. Preserve audit and incident details without recording tokens, codes or private keys.

The app sees the client's IP through Uvicorn only when requests come from the loopback Caddy proxy configured with `--proxy-headers --forwarded-allow-ips=127.0.0.1`. Do not trust public `X-Forwarded-For` input or expose Uvicorn directly. On client IP change the current session is rejected and Entra sign-in is required again. IT's Conditional Access, not the application, determines whether that new sign-in needs MFA. Different corporate VPN/proxy paths must be included in IT's trusted-location testing.

References: [Microsoft certificate credentials](https://learn.microsoft.com/en-us/entra/identity-platform/certificate-credentials), [Entra app roles](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps), [application assignment](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/what-is-access-management), and [Conditional Access network signals](https://learn.microsoft.com/en-us/entra/identity/conditional-access/concept-assignment-network).
