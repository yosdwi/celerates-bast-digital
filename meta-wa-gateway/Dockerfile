FROM node:20.18.1-bookworm-slim

ENV NODE_ENV=production META_WA_GATEWAY_HOST=0.0.0.0 META_WA_GATEWAY_PORT=8090 BOT_DATA_DIR=/data

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /opt/meta-wa-gateway --create-home --shell /usr/sbin/nologin app

WORKDIR /opt/meta-wa-gateway
COPY meta-wa-gateway/package*.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY --chown=10001:10001 meta-wa-gateway/*.js ./

RUN mkdir -p /data/evidence-uploads /data/exports && chown -R 10001:10001 /data

USER 10001:10001
EXPOSE 8090
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "server.js"]
