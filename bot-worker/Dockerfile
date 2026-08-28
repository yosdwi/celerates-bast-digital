# Stateless HTTP wrapper around the `digital-bast` CLI. Built FROM the app
# image (needs the CLI + its Python dependencies on PATH) and rebuilt on
# every deploy, same as the combined bot-bridge image was before the split --
# safe here because this service holds no WhatsApp session state at all; see
# ../wa-session/Dockerfile for the piece that does and is deliberately kept
# separate from the app image.
ARG APP_IMAGE=digital-bast:local
FROM ${APP_IMAGE} AS base

USER root

# Node 20 from NodeSource, not Debian bookworm's `nodejs` package: bookworm
# ships Node 18. No Baileys here, but keeping the same Node version as
# wa-session avoids two different runtimes to reason about.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/digital-bast/bot-worker
COPY bot-worker/package.json bot-worker/package-lock.json ./
RUN npm ci --omit=dev

COPY bot-worker/server.js ./

# Shared with wa-session for evidence-upload/export file hand-off -- this
# service has no session of its own, so no /data/auth here.
RUN mkdir -p /data/evidence-uploads /data/exports \
    && chown -R 10001:10001 /data /opt/digital-bast/bot-worker

USER 10001:10001
EXPOSE 8091
CMD ["node", "server.js"]
