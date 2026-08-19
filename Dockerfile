FROM python:3.12.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /usr/local/bin/uv
ENV UV_FROZEN=1 UV_NO_DEV=1 UV_NO_EDITABLE=1 UV_PYTHON_DOWNLOADS=0 UV_PROJECT_ENVIRONMENT=/opt/digital-bast/.venv

WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync

FROM python:3.12.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/digital-bast/bin:/opt/digital-bast/.venv/bin:$PATH PYTHONPATH=/opt/digital-bast/src TZ=Asia/Jakarta

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates curl tini unixodbc \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /opt/digital-bast --create-home --shell /usr/sbin/nologin app

COPY --from=builder --chown=10001:10001 /opt/digital-bast/.venv /opt/digital-bast/.venv
COPY --chown=10001:10001 src /opt/digital-bast/src
COPY --chown=10001:10001 templates /opt/digital-bast/templates
COPY --chown=10001:10001 static /opt/digital-bast/static
COPY --chown=10001:10001 migrations /opt/digital-bast/migrations
COPY --chown=10001:10001 alembic.ini /opt/digital-bast/alembic.ini
# Operational one-offs run inside the container: the roster seed, the schedule
# CSV import, the direct PAMA attendance load. Without these here, running them
# means bind-mounting the host checkout into a throwaway container.
COPY --chown=10001:10001 scripts/*.py /opt/digital-bast/scripts/
COPY --chown=root:root scripts/container-entrypoint.sh /opt/digital-bast/bin/container-entrypoint
RUN chmod 0555 /opt/digital-bast/bin/container-entrypoint

WORKDIR /opt/digital-bast
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--", "container-entrypoint"]
CMD ["uvicorn", "digital_bast.web.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
