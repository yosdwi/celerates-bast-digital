# Deployment and rollback

Before first deployment, verify that the production server root filesystem has at least 20 GB available with `df -h /`. `scripts/preflight.sh` enforces the available-space threshold and also verifies Docker, Compose, secret presence, permissions, and Compose validity.

The release workflow builds an immutable SHA-tagged image, publishes provenance and an SBOM, deploys staging, and runs the same migration, shadow, and health gates used in production. Configure required reviewers on the GitHub `production` environment. Workflow concurrency and the host `flock` prevent overlapping releases.

On the host, use `APP_IMAGE=<immutable-image> scripts/deploy.sh`. Use `--dry-run` to inspect actions. The script preserves the active slot until the inactive web and worker start, web health passes, shadow traffic succeeds, and Alembic succeeds. It switches Nginx, checks public application health, restores the old route on failure, and leaves both slots running so the previous slot remains rollback-ready until an explicit later cleanup.

Use `scripts/rollback.sh --dry-run` before `scripts/rollback.sh`. Rollback requires the previous slot to remain healthy. A failed or backward-incompatible database migration is not automatically downgraded; restore compatibility with a forward migration or perform the rehearsed database restore procedure. Never run `docker compose down`, delete volumes, or prune images during rollback.

If deploy fails before switching, inspect the inactive slot and migration output while production remains on the active slot. If health fails after switching, verify the automatic route restoration. If the deployment lock is held, identify the running workflow or process instead of deleting the lock file.
