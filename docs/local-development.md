# Local development

Install Python 3.12 and `uv`, then run `uv sync --all-groups`. Create `secrets/` from the names in `.env.example`; use development-only values, never production credentials. Set `SECRETS_GID` to a group shared by the local user and containers, assign each secret file to that group, and set every file to mode `0640`.

Set `NOCODB_BASE_URL`, then validate the configuration:

Ensure the externally managed legacy network exists before starting the stack (create it once with `docker network create digital-bast-network` if needed).

```sh
docker compose -f compose.yaml -f compose.local.yaml --profile blue config --quiet
```

Start the blue local stack:

```sh
docker compose -f compose.yaml -f compose.local.yaml --profile blue up -d --build
```

The web endpoint is `http://127.0.0.1:8080`; Prefect is `http://127.0.0.1:4200`. Prefect requires the `username:password` value from `secrets/prefect_api_auth` for Basic Auth.

For a remote host, create an SSH tunnel using placeholders only:

```sh
ssh -N -L 127.0.0.1:4200:127.0.0.1:4200 <ssh-user>@<server-host>
```

Then open `http://localhost:4200` and authenticate with the `username:password` value in the remote `prefect_api_auth` secret. If `PREFECT_PORT` is customized, use that port on both sides of the tunnel. Run `scripts/smoke.sh`, inspect `docker compose ps`, and stop with `docker compose --profile blue down`. Do not use `down -v` unless intentionally deleting local databases.
