# Azure deployment for Howe Robinson

**HRP SSO migration notice (1 October 2026):** the personal Microsoft
registration and owner approval flow described below remain the current live
configuration. For the planned HRP-owned single-tenant replacement, follow
[HRP Microsoft Entra SSO handoff and cutover](hrp-entra-sso.md). In particular,
the instruction below not to create a new Microsoft application applies only
to the existing personal-account deployment, not the HRP migration.

Updated 29 September 2026. Application deployment and live Microsoft owner
sign-in succeeded. HTTPS liveness, anonymous API denial, administrator access
management, and session/account persistence across a service restart passed.

Provisioned resource group: `howe-robinson-dashboard_group`.
VM: `howe-robinson-dashboard`, Central India, Ubuntu 24.04,
`Standard_B2als_v2`. Public IP: `4.213.126.137`.
Verified DNS: `howe-robinson-dashboard.centralindia.cloudapp.azure.com`.
The exact HTTPS callback is saved on the existing Microsoft registration.
Only HTTP/HTTPS are exposed. The approved temporary current-IP SSH transfer
rule was removed after verification. The one-time administrator bootstrap
settings were removed from the root-owned mode 0600 server configuration.
The existing AISSTREAM credential has not been transferred: approval is pending.
The subscription remains on its trial plan; no upgrade was performed.

## Hosting choice

Use one Ubuntu 24.04 LTS VM (initial target: Standard_B2als_v2, 2 vCPU, 4 GiB RAM)
with a persistent Standard SSD managed OS disk and a Standard static public IP.
The portal draft lists this size as available and completes validation. Confirm
pricing and user approval before provisioning. Keep the VM and
disk in the same approved region; Central India is the initial preference.
Do not use spot instances, reservations, autoscaling, or paid Bastion for this
deployment. Keep the existing bunker-price-monitor and Render service intact.

The application uses SQLite for access and AIS/archive state. Microsoft says
App Service Linux's network filesystem cannot acquire SQLite exclusive locks:
https://learn.microsoft.com/en-us/troubleshoot/azure/app-service/faqs-app-service-linux-new#can-i-use-a-file-based-database-like-sqlite-with-my-linux-web-app
The app therefore fails closed on App Service rather than silently storing
approvals in an ephemeral directory. A VM's managed block disk fits the current
single-worker architecture. A future App Service migration requires migrating
all persistent database consumers to supported database services first.

## Review before creating resources

Resource group: `howe-robinson-dashboard_group`; VM: `howe-robinson-dashboard`.
Use a dedicated virtual network and network security group. Allow inbound TCP
80 and 443 only. Keep TCP 8000 and SSH closed to the Internet; use Azure Run
Command initially, or a separately approved restricted SSH rule. No public
access to storage databases. Authentication remains mandatory on the app.

Compute, managed disk, public IP and outbound traffic can incur charges. Azure
portal currently shows trial credit expiring 10 October 2026; services may pause
at expiry. Subscription upgrade is a separate user decision. No cost estimate
is a spending cap; budgets alert rather than automatically stop resources.
Confirm the exact portal quote before creation.

Microsoft retail API retrieved on 29 September 2026 quotes Central India Linux
Standard_B2als_v2 at INR 2.3504/hour, E6 LRS 64 GiB at INR 504.4842/month and Standard
IPv4 static public IP at INR 0.4777/hour. At 730 hours/month, the baseline is
INR 2,569.00/month before tax, disk operations, traffic and account-specific
pricing. This is a review estimate, not an approved charge or guaranteed quota.

## Package and install

Run `python scripts/package_azure.py <outside-repo>/dashboard.zip`. The allowlist
packages root Python modules, requirements, official/curated data, frontend,
runtime scripts and the bundled tracker zip. It excludes `.env`, local access
records, retained AIS, uploads, certificates, private keys, logs and test caches.
The adjacent manifest hashes each packaged file. Preserve the package hash.

Use the static public IP's DNS label to obtain the actual
`<label>.<region>.cloudapp.azure.com` hostname. Do not guess this hostname; read
it from Azure after configuring DNS. Register the exact HTTPS `/auth/callback`
URL on the existing Microsoft application while retaining localhost and Render.
Do not create a new Microsoft application: subjects are application-specific.

Transfer only explicitly approved secrets to this VM. Create root-owned mode
0600 `/etc/hrp/dashboard.env` with `AUTH_BASE_URL=https://<actual-host>`, the
existing `MICROSOFT_CLIENT_ID` and secret. Add existing AIS/news API credentials
only with user-approved transfer scope. Never put secrets in custom data, ARM
parameters, command history, logs, screenshots, ZIP packages or source control.
The VM runtime injects `APP_ENV=production` and `HRP_STORAGE_DIR=/var/lib/hrp`.

Upload the reviewed ZIP and `scripts/install_azure_vm.sh` through an authorized
private transfer, then run the installer with the package path and DNS hostname.
It installs distro packages, creates an unprivileged application user, one
Uvicorn worker, systemd restart supervision, and Caddy HTTPS termination. Caddy
proxies to loopback only and does not enable request access logging.
https://caddyserver.com/docs/automatic-https

Keep approved-user records on the VM's persistent disk. Do not transfer browser
sessions. Bootstrap the owner's previously validated exact Microsoft issuer
and subject using temporary server environment values, then remove them after
the one-time bootstrap succeeds. Do not approve by email alone.

## Acceptance and operations

- HTTPS health returns minimal liveness; valid TLS certificate and HTTP redirect.
- Anonymous dashboard redirects to sign-in; direct APIs and static data denied.
- Actual Microsoft callback validates and approved administrator opens the map.
- Administrator access panel works; a viewer cannot upload, refresh or approve.
- AIS/weather collection operates without browser sessions when source keys exist.
- Owner access and retained data survive service and VM restart.
- CPU/RAM and disk usage fit the selected instance; inspect logs without tokens.

SQLite backups must use its backup API or happen while the service is stopped.
Do not copy live WAL/database files blindly. Keep backups outside the VM before
disk changes. Retain the managed disk when deleting/recreating the VM; disks and
public IP can continue to cost money after compute is stopped. Use deallocation
to stop compute billing. No automatic notifications are added by this release.
