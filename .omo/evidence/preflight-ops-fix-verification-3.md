# Direct boundary verification

Verification run: 2026-08-03
Working directory: `/mnt/d/Github/celerates/digital-bast/v2-prod`

The following scenarios were executed with temporary fake `df` and `docker` binaries. The trap removed the temporary directory after the run.

```text
=== fake df 75GB total / 22GB free ===
status=78
required file unavailable: /tmp/tmp.X51odC3V4Z/missing/postgres_password
=== fake df 75GB total / 19GB free ===
status=70
root disk has less than 20GB available
=== retention SQL ===
status=0
begin;
delete from nocodb_audit_events where created_at < now() - interval '30 days';
delete from generation_plans where created_at < now() - interval '30 days';
commit;
=== check-ops source scan ===
rg_status=1
=== retention dry run ===
DRY-RUN delete NocoDB audit snapshots older than 30 days
DRY-RUN delete generation_plans older than 30 days
status=0
```

Judgment: 75 GB total with 22 GB available passes the disk gate and reaches the missing-secret prerequisite (status 78); 19 GB available fails the retained free-space gate with status 70. Captured SQL names `generation_plans` and contains no `generated_plans`. The source scan returns no match for the prior `postgres-init.sh:8` false-positive pattern. Retention dry-run uses the migrated table name.

DoneClaim: direct boundary behavior and generated SQL are independently verified with captured output.
