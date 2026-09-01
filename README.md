# celerates-bast-digital

## Setup

```
uv sync
playwright install chromium
```

Chromium is required by `digital-bast generate-bast` (headless PDF export via
`src/digital_bast/infrastructure/pdf_export.py`).

## WhatsApp

`meta-wa-gateway/` is the sole WhatsApp transport. It integrates directly with
the official Meta WhatsApp Cloud API, exposes the signed callback at
`/webhooks/whatsapp`, and delegates unchanged Digital BAST business workflows
to `bot-worker/`. See [docs/bast-bot.md](docs/bast-bot.md) for architecture and
production activation, including interactive buttons/lists and utility
templates.
