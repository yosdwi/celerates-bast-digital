# WhatsApp session holder: Baileys + a setup page. Deliberately NOT built
# FROM the app image -- it has no `digital-bast` CLI dependency at all
# (bot-worker does the CLI shelling, reached over HTTP), so this image only
# rebuilds when wa-session/ itself changes, never from an app-only deploy.
# That decoupling is the whole point of this service existing separately:
# recreating the container that holds the live Baileys socket forces a
# reconnect, and WhatsApp's anti-abuse system revokes the session after a
# few rapid reconnects -- which is what coupling it to every app deploy
# caused in production.
FROM node:20-slim

WORKDIR /opt/wa-session

RUN groupadd -g 10001 wasession \
    && useradd -u 10001 -g wasession -M -s /usr/sbin/nologin wasession

COPY wa-session/package.json wa-session/package-lock.json ./
RUN npm ci --omit=dev

COPY wa-session/server.js wa-session/mention.js wa-session/greeting.js wa-session/outbound.js ./

# The Baileys auth session lives on a volume shared with bot-worker (which
# needs it for evidence-upload/export file hand-off, not for the session
# itself) so pairing survives redeploys of this service.
RUN mkdir -p /data/auth && chown -R 10001:10001 /data /opt/wa-session

USER 10001:10001
ENV BOT_AUTH_DIR=/data/auth
EXPOSE 8090
CMD ["node", "server.js"]
