# WhatsApp bridge image: the app runtime plus Node.
#
# server.js drives the bot by shelling out to the `digital-bast` CLI, so the
# two have to share a filesystem. Running the bridge on the host and reaching
# into a container would mean either a docker socket mount or a shared export
# directory; putting Node in the app image avoids both.
FROM digital-bast:local AS base

USER root

# Node 20 from NodeSource, not Debian bookworm's `nodejs` package: bookworm
# ships Node 18, and the pinned @whiskeysockets/baileys refuses to install on
# anything below 20 ("This package requires Node.js 20+ to run reliably"), so
# `npm ci` fails outright.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/digital-bast/bot-bridge
COPY bot-bridge/package.json bot-bridge/package-lock.json ./
RUN npm ci --omit=dev

COPY bot-bridge/server.js bot-bridge/mention.js ./

# The Baileys auth session and generated exports live on a volume so the
# paired WhatsApp session survives redeploys -- re-pairing by QR would take
# the bot offline until someone scans it.
RUN mkdir -p /data/auth /opt/digital-bast/bot-bridge/data/exports \
    && chown -R 10001:10001 /data /opt/digital-bast/bot-bridge

USER 10001:10001
ENV BOT_AUTH_DIR=/data/auth
EXPOSE 8090
CMD ["node", "server.js"]
