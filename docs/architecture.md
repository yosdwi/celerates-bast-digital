# Operations architecture

Digital BAST runs as a private container network behind a loopback-only Nginx endpoint. A Cloudflare Tunnel connects that endpoint to Cloudflare Access. PostgreSQL and Redis have no public network route. The application, Prefect API, Prefect services, and Prefect workers use mounted secret files and an internal network.

The base stack contains PostgreSQL, Redis, the Prefect API with background services disabled, a separate Prefect services process, and Nginx. Application web, Prefect worker, and RunnerDeployment processes have blue and green profiles. Only the active slot serves traffic and processes application work. During delivery both web slots run until the inactive slot passes health, readiness-shadow, and migration gates; the inactive worker and runner then start. Nginx reloads onto the new slot, public readiness is checked, and only then is the old slot stopped.

All containers use resource limits and health checks. Application containers use UID/GID 10001, a read-only root filesystem, dropped Linux capabilities, no-new-privileges, and bounded tmpfs mounts. Scheduling and container time are fixed to `Asia/Jakarta`.

Cloudflare Access is the external identity boundary. It must protect the application hostname and the Prefect hostname with deny-by-default policies and short sessions. Prefect Basic Auth remains enabled as an independent control. The Cloudflare tunnel origin points to `http://127.0.0.1:8080`; the Prefect server is published only on `127.0.0.1:${PREFECT_PORT:-4200}`. For remote administration, tunnel that loopback port over SSH and authenticate at `http://localhost:4200` with the `username:password` value in `prefect_api_auth`.
