# Server preflight

Provision a supported Linux host with a root filesystem of at least 150 GB, at least 20 GB free, synchronized time, Docker Engine with Compose v2, `age`, `rclone`, `curl`, and `flock`. Permit inbound SSH only from the administrative path. Do not expose PostgreSQL, Redis, application, or Prefect ports publicly. Bind the Cloudflare Tunnel to loopback origins.

Create a non-root deployment account, restrict Docker access to that account, install the repository under a dedicated path, and create secret files with safe ownership and permissions. Pin the production image to its digest or commit SHA. Configure log rotation, disk alerts, Docker daemon restart behavior, the daily backup timer, daily retention timer, and monthly restore-test reminder.

Run `scripts/preflight.sh`, `docker compose --profile blue config --quiet`, and `scripts/deploy.sh --dry-run`. Confirm Cloudflare Access denies an unauthenticated request, an authorized user reaches the application, Prefect also challenges with Basic Auth, and audit events are retained. Record the image digest, active slot, backup timestamp, restore-test timestamp, and operator before enabling production traffic.
