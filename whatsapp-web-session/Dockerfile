# Candidate replacement for wa-session -- see README.md and
# docs/wa-session-whatsapp-web-js-migration-plan.md for validation history.
# Deliberately NOT built FROM the app image, mirroring
# whatsmeow-session/Dockerfile: this holds a live session, so it must never
# rebuild just because app code changed. Build context is the repo root
# (matching wa-session/bot-worker's own compose.yaml entries), so COPY paths
# below are prefixed with whatsapp-web-session/.
#
# Puppeteer's OWN bundled Chrome download, not Debian's `chromium` package.
# Tried system Chromium first to save disk (see docs/wa-session-whatsapp-web-js-
# migration-plan.md, "Resource footprint") but it reproduces a known
# whatsapp-web.js failure: client authenticates, `loading_screen` reaches
# 100%, and `ready` never fires -- confirmed against
# https://github.com/wwebjs/whatsapp-web.js/issues/127084 (system Chromium
# v144 hangs; Puppeteer's own bundled Chrome works). The `chromium` apt
# package is still installed for its runtime shared libraries (libnss3,
# libgbm1, etc.) -- Puppeteer's downloaded Chrome links against those --
# but is deliberately not what gets executed.
FROM node:20-bookworm-slim

RUN groupadd -g 10001 wwjs \
    && useradd -u 10001 -g wwjs -M -s /usr/sbin/nologin wwjs \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       chromium ca-certificates fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

ENV HOME=/tmp \
    npm_config_cache=/tmp/.npm \
    PUPPETEER_CACHE_DIR=/opt/whatsapp-web-session/.cache/puppeteer

WORKDIR /opt/whatsapp-web-session
COPY whatsapp-web-session/package.json ./
RUN npm install --omit=dev --no-audit --no-fund

COPY whatsapp-web-session/patch-stream-mode-enum.js whatsapp-web-session/patch-serialized-rename.js ./
RUN node patch-stream-mode-enum.js && node patch-serialized-rename.js

COPY whatsapp-web-session/server.js whatsapp-web-session/state.js whatsapp-web-session/bridge.js whatsapp-web-session/helpers.js whatsapp-web-session/stub-worker.js ./

RUN mkdir -p /data/auth-whatsapp-web-js /data/evidence-uploads /data/exports \
    && chown -R 10001:10001 /data /opt/whatsapp-web-session

USER 10001:10001
EXPOSE 8090
CMD ["node", "server.js"]
