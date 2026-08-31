# WhatsApp session holder: whatsmeow + a setup page. Replaces wa-session/'s
# Baileys implementation with the same deployment shape -- deliberately NOT
# built FROM the app image (no `digital-bast` CLI dependency; bot-worker does
# the CLI shelling over HTTP), so this image only rebuilds when
# whatsmeow-session/ itself changes, never from an app-only deploy. Recreating
# the container that holds the live WhatsApp session forces a reconnect, and
# WhatsApp's anti-abuse system can revoke a session after a few rapid
# reconnects -- see scripts/deploy-wa-session.sh, which this image is built by.
FROM golang:1.26-bookworm AS builder

WORKDIR /src

COPY whatsmeow-session/go.mod whatsmeow-session/go.sum ./
RUN go mod download

COPY whatsmeow-session/ ./
# CGO is required: the durable SQLite session store (go-sqlite3) is a cgo
# binding, not pure Go.
RUN CGO_ENABLED=1 go build -trimpath -o /out/digital-bast-whatsmeow .

FROM debian:bookworm-slim

RUN groupadd -g 10001 wasession \
    && useradd -u 10001 -g wasession -M -s /usr/sbin/nologin wasession \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/whatsmeow-session
COPY --from=builder /out/digital-bast-whatsmeow ./digital-bast-whatsmeow

# A fresh, whatsmeow-only auth directory on the volume shared with
# bot-worker (which needs it for evidence-upload/export file hand-off, not
# for the session itself) -- never the old Baileys auth/ path. Baileys
# credentials are incompatible with whatsmeow and stay in place as rollback
# data; this cutover requires exactly one new pairing.
RUN mkdir -p /data/auth-whatsmeow && chown -R 10001:10001 /data /opt/whatsmeow-session

USER 10001:10001
ENV BOT_AUTH_DIR=/data/auth-whatsmeow
EXPOSE 8090
CMD ["./digital-bast-whatsmeow"]
