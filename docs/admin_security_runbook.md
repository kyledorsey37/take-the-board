# Admin security runbook

Non-local Admin access requires a staff account plus a confirmed TOTP device
provided by `django-otp`. On first access, sign in at `/admin/`, open the
displayed authenticator setup URI in an approved authenticator, and submit the
current code. The device is stored in the application database; keep recovery
and device replacement procedures restricted to the deployment owner.

Set `TAKEBOARD_ENVIRONMENT=staging` or `production`, install the pinned
requirements, run migrations, and verify each staff member's enrollment before
opening Admin access. Do not use local settings or the local bypass for a
public host. Admin login attempts are throttled through the shared cache and
fail closed if that cache is unavailable outside local development.

The repository verification environment must install `requirements.txt` before
running Django checks; Docker daemon access and a running web container are
also required for the deployment smoke test.

External deployment work remains required: protect `/admin/` with an ALB/WAF
allowlist, VPN, or SSO; configure staff enrollment ownership and recovery;
route repeated-login and MFA/provider failures to monitored alert destinations;
and verify edge headers without weakening the application policy.
