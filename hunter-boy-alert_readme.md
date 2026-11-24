# Hunter Boy Gaming Alert

## Purpose

A public one-tap page that forwards a gaming alert to the existing Home Assistant webhook and enforces a server-side global 30-minute cooldown.

## Architecture

Browser -> Cloudflare proxy/Tunnel -> Caddy -> `hunter-boy-alert:8080` -> Home Assistant over the server's Tailscale route (`http://192.0.2.1:8123`). The app serializes activation attempts in SQLite, forwards the webhook, and records a cooldown only after a 2xx webhook response. GET requests only render/read status.

## Location

- Source: `/home/leandro/services/hunter-boy-alert` (production working copy); public sanitized source snapshot: `https://github.com/Noxist/hunter-boy-alert`, branch `main`. The publication checkout is separate; reconcile local changes before future updates.
- Persistent state: `/home/leandro/service_data/hunter-boy-alert/cooldown.sqlite3`.

## Runtime

Docker Compose project `hunter-boy-alert`, on the existing external `shared_services` network.

## Services and Containers

| Container | Purpose |
|---|---|
| `hunter-boy-alert` | Static UI, JSON API, serialized webhook forwarding, and persistent cooldown. |

## Networking

- Container listens on TCP 8080, exposed only on `shared_services`.
- No host port is published.
- Caddy is already host-published on TCP 80/443 for existing services; this app adds no host binding.
- Outbound HA connection uses the server's Tailscale route to `192.0.2.1:8123`.
- Cloudflare Tunnel forwards the exact hostname to Caddy; unrelated ingress rules remain unchanged.
- Remotely managed Tunnel configuration advanced from version 29 to 30 with only the `webhook.nox007.tech -> http://caddy:80` ingress inserted before the existing 404 fallback.

## Public Access

- Hostname: `https://webhook.nox007.tech`.
- Cloudflare DNS is proxied to the existing Tunnel; Cloudflare edge TLS provides HTTPS, Tunnel origin traffic is HTTP to Caddy.
- Cloudflare Access is not enabled by explicit product requirement.
- Visitors do not authenticate. The activation page and API are public; global rate limiting is enforced by SQLite on the server.
- The underlying Home Assistant webhook remains a bearer secret and may be directly callable through its separate Nabu Casa URL by anyone who knows the webhook ID. The app cooldown does not cover requests that bypass this website. Preventing that bypass requires an authorized Home Assistant automation change; the HA configuration API was not available to this deployment.
- No direct-IP route was created for this hostname; the Caddy catch-all remains deny-by-default.

## Configuration

- Compose: `docker-compose.yml`.
- Caddy route: `/home/leandro/services/Caddyfile` (`http://webhook.nox007.tech`).
- Tunnel and DNS route are remotely managed by Cloudflare.
- App source: `server.py`; static interface: `web/index.html`.
- Runtime reads the webhook URL from `/run/secrets/ha_webhook_url`. Configure `HA_WEBHOOK_PREFIX` separately to the trusted Home Assistant origin followed by `/api/webhook/`; no webhook ID belongs in this setting. An empty or mismatched prefix fails closed. Addresses in this repository use documentation placeholders and must be replaced by deployment-specific configuration.

## Secrets

| Name | Purpose | Storage location | Scope/Notes |
|---|---|---|---|
| `ha_webhook_url` | Trigger the existing Hunter Boy automation | `/etc/server-secrets/hunter-boy-alert/ha_webhook_url` | File mode 0600, directory mode 0700; mounted read-only. Owner UID 1000 so the non-root app process can read the bind-mounted Compose secret. Contains the private Tailscale HTTP endpoint. Never copy to source, logs, screenshots, or handoff ZIP. |

## Persistent Data

SQLite database `/home/leandro/service_data/hunter-boy-alert/cooldown.sqlite3` stores the last successful delivery timestamp. The database is bind-mounted and survives container rebuilds/restarts.

## Backup

Back up the Compose/source/Caddy files and `cooldown.sqlite3`. Use SQLite's online backup API or stop only `hunter-boy-alert` before copying the database. Back up the secret separately under restricted root-only handling; it is excluded from ordinary archives and handoffs.

## Restore

Restore project source and the database to the documented paths, ensure the secret is present with the documented ownership/modes, validate Compose and Caddy, then start only `hunter-boy-alert` and reload Caddy if its route changed.

## Deployment / Start / Stop

```bash
cd /home/leandro/services/hunter-boy-alert
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 hunter-boy-alert
docker compose stop hunter-boy-alert
```

To restart after an app-only change: `docker compose up -d --build hunter-boy-alert`. Do not run `down -v`; there are no disposable volumes.

To reset the website cooldown manually from a terminal, run:

```bash
python3 /home/leandro/services/hunter-boy-alert/reset-cooldown.py
```

This atomically clears only the website's SQLite cooldown, sends no HA request, and makes the button available. An open page picks up the reset within 10 seconds; a new page sees it immediately. If the optional HA-side cooldown patch is later installed, reset its HA helper separately as well.

## Update Procedure

Review changes, run `python3 -m unittest discover -s tests -v`, validate `docker compose config --quiet`, rebuild only this container, and verify `/health`, `/api/status`, and the public page. Keep the shared Caddy and Tunnel changes scoped to this hostname.

## Health Checks

- Docker health check: GET `http://127.0.0.1:8080/health` from inside the container.
- App health JSON is `{ "healthy": true }`.
- `GET /api/status` returns `available` and `remaining_seconds` without triggering HA.
- `POST /api/activate` returns 200 on a 2xx HA webhook response, 429 with `remaining_seconds` while cooling down, or 502 when HA does not accept the request.
- Mock tests: 4 passed, covering GET safety, 12-way concurrent activation, persistence across DB reopen, failed-delivery behavior, and the operator reset command.
- Live verification: one controlled public POST received HTTP 200 from Home Assistant; public status then showed cooldown active. Ten simultaneous follow-up requests returned HTTP 429. The container was restarted and the cooldown remained active. No second HA trigger was sent.
- Cloudflare browser checks: desktop Chrome and Android Pixel viewport screenshots were reviewed. Both returned HTTPS 200 with TLS verification successful; the responsive layout showed the button and countdown without horizontal overflow. Browser tests with mocked API responses verified loading, success/countdown, and error/re-enabled-button states.

## Logs

Use `docker compose logs --tail=100 hunter-boy-alert`. Logs contain method/path, result status, and exception class only; never enable request-body or secret-URL logging.

## Security Model

The application runs as UID/GID 1000 with a read-only root filesystem, dropped Linux capabilities, no-new-privileges, bounded memory/PIDs, private Docker networking, no host port, and a read-only mounted secret. SQLite `BEGIN IMMEDIATE` serializes simultaneous global requests. Failed HA responses do not start cooldown. The UI uses no third-party resources and GET never activates.

## Security Exceptions

- Public anonymous alert activation is intentional per the product requirement; no Cloudflare Access or login is configured. The 30-minute website limit is global and server-enforced.
- The HA webhook is a bearer endpoint. Its separate public Nabu Casa URL may bypass the website cooldown; this residual risk remains until HA's trigger/automation is updated with an authorized mechanism.

## Rollback

1. Remove only `http://webhook.nox007.tech` from Caddyfile and reload Caddy.
2. Delete only the `webhook.nox007.tech` ingress rule from the existing Cloudflare Tunnel and the matching DNS record.
3. From `/home/leandro/services/hunter-boy-alert`, run `docker compose stop hunter-boy-alert && docker compose rm hunter-boy-alert` (no `-v`).
4. Restore Caddy with `cp /home/leandro/services/Caddyfile.bak-hunter-boy-alert-20261021 /home/leandro/services/Caddyfile` and `docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile`. Keep SQLite and the secret unless separately authorized for deletion.

## Troubleshooting

- Container unhealthy: inspect `docker compose logs` and `docker inspect hunter-boy-alert --format '{{json .State.Health}}'`.
- 502: check Tailscale reachability to `192.0.2.1:8123` and verify the protected secret file's metadata without printing its contents.
- 429: expected during the global cooldown; check the countdown and `Retry-After`.
- If the browser reports a connection interruption after clicking, the request may still have reached Home Assistant. The page checks the server cooldown and warns not to retry blindly when the outcome is uncertain; verify with Leandro before another attempt.
- Caddy/Tunnel 404: verify exact hostname in Caddy and remotely managed Tunnel ingress; the catch-all is intentionally retained.

## Maintenance Notes

- HA REST configuration endpoints returned 401. No HA automation was changed. `home-assistant-notification-patch.yaml` adds the Pixel notification before existing game actions, uses `continue_on_error`, preserves later actions, and requires removing presence gating. `home-assistant-cooldown-patch.yaml` provides helper and automation fragments for HA-side cooldown protection; merge and verify them in Home Assistant.
- A visitor who already knows the webhook ID can invoke the separate Nabu Casa webhook directly and bypass this app's website cooldown. Home Assistant must enforce its own cooldown or restrict that trigger to trusted sources to eliminate this bypass; the HA config access available here did not permit that change.
- This bypass is documented and not represented as fixed. The HA-side fragment is an unverified manual patch because the existing automation YAML/mode/helper state could not be inspected.
- Notification title/message are fixed by the requested patch; priority is high. Notification delivery has not been claimed or verified.
- Future authentication can be added at the API boundary without changing the static UI, cooldown database, or webhook adapter.

## Last Reviewed

2026-10-21 — Initial deployment, public-route verification, PC icon/status design update, operator cooldown reset command, and recovery messaging for interrupted activation responses.

## Private GitHub publication

The separate publication checkout is `/home/leandro/ai_overlord/results/rootserver-finalisierung-20261117/hunter-boy-publication` and tracks `origin/main`. The production working copy retains its independent Git history and dirty changes. For each update, fetch and inspect the remote head, compare the production files against that checkout, and copy only individually reviewed source/documentation files; exclude secrets, databases, runtime data, generated files and private information. Run the relevant isolated tests and a secret scan on the exact intended tree, review the staged diff and commit, then push a normal fast-forward and compare the GitHub tree and commit. Resolve any remote divergence explicitly; never force-merge the independent histories or overwrite unreviewed changes. Preserve both checkouts until their recovery paths are independently verified.
