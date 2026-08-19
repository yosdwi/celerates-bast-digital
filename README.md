# celerates-bast-digital

## Setup

```
uv sync
playwright install chromium
```

Chromium is required by `digital-bast generate-bast` (headless PDF export via
`src/digital_bast/infrastructure/pdf_export.py`).
