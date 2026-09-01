# Meta WhatsApp Cloud API gateway

The only WhatsApp transport in Digital BAST. It uses the official Meta Graph
API and signed WABA webhooks; it never opens a WhatsApp Web session and has no
QR, pairing code, linked-device credentials, or reconnect lifecycle.

## Public and internal endpoints

- `GET /webhooks/whatsapp` — Meta callback challenge verification.
- `POST /webhooks/whatsapp` — raw-body `X-Hub-Signature-256` verified webhook.
- `GET /health` — process liveness.
- `GET /ready` — required configuration and PostgreSQL readiness.
- `GET /internal/v1/status` — authenticated provider status for TalentOps.
- `POST /internal/v1/messages` — authenticated outbound compatibility API.

Only `/webhooks/whatsapp` is public through Nginx. Internal endpoints remain on
the Docker backend network and require the shared bridge token.

## Behavior

- Meta `wa_id` is normalized to the existing canonical phone JID only at the
  worker boundary, preserving all current talent/operator bindings.
- Historical linked-device-only `@lid` values are deliberately rejected as
  outbound recipients; those users complete the existing NRP/name onboarding
  once from their Meta `wa_id` so no provider-specific identifier is guessed.
- Up to three compact actions become native reply buttons; larger menus become
  list messages. Typed numeric replies remain supported by existing workflow
  logic.
- A Talent Mobile URL in a worker reply becomes a native CTA URL button.
- Incoming image/document media is downloaded through the Media API and handed
  to the unchanged evidence workflow.
- Generated files are uploaded through the Media API and removed only after a
  successful Meta send.
- Inbound `wamid` is durably queued before webhook acknowledgement; stale or
  failed work is recovered after restart. Outbound `request_id` claims are
  durable in PostgreSQL.
- `sent`, `delivered`, `read`, and `failed` webhooks are retained and correlated
  with existing follow-up/outbox rows. A periodic reconciliation handles the
  race where Meta reports delivery before the application commits its row.

## Required configuration

Non-secret environment values:

```env
META_GRAPH_VERSION=v26.0
META_WA_PHONE_NUMBER_ID=
META_WA_WABA_ID=
META_WA_DISPLAY_PHONE_NUMBER=
META_WA_PUBLIC_BASE_URL=https://bast.example.com
META_DEFAULT_UTILITY_TEMPLATE=bast_action_required_v1
META_TEMPLATE_LANGUAGE=id
```

Secret files:

```text
meta_wa_access_token
meta_app_secret
meta_webhook_verify_token
app_database_dsn
sync_ingest_token
```

Use a production System User token with the required WhatsApp permissions.
Never commit token values.

Validate the production phone, token, and approved template without changing
Meta state, then subscribe the app to the WABA:

```bash
scripts/meta-wa-setup.sh check
scripts/meta-wa-setup.sh subscribe
```

Set the App Dashboard webhook callback to the printed HTTPS URL and use the
same value stored in `meta_webhook_verify_token` as its verify token. Subscribe
the webhook field `messages`.

## Utility template contract

Create and approve `bast_action_required_v1` as an Indonesian utility template
whose body accepts one text parameter. All application-initiated TalentOps,
scheduled Talent, and PMO messages send the existing deterministic message as
that parameter. Free-form text is reserved for replies to inbound messages
inside the customer-service window.

## Local tests

```bash
npm ci
npm test
```
