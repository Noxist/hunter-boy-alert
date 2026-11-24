# Project instructions

Follow `/home/leandro/server-standards/SECURITY_POLICY.md`, `/home/leandro/server-standards/PROJECT_STANDARD.md`, and this project's `README.md`.

- Keep the Home Assistant webhook URL only in `/etc/server-secrets/hunter-boy-alert/ha_webhook_url`.
- Preserve `/home/leandro/service_data/hunter-boy-alert/cooldown.sqlite3`.
- No host ports; attach only to `shared_services`; reload/recreate only this app or Caddy when required.
- Public activation is intentional and documented as a security exception; do not add auth without a future access-control design.
