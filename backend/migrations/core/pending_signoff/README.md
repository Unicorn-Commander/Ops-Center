# core/pending_signoff — DANGEROUS migrations (NOT auto-applied)

`core_migrations.run_core_migrations()` only applies `migrations/core/*.sql`. It
**never** descends into this directory. SQL here changes a **primary-key type or
an identity-column type** (e.g. `uuid` ↔ `integer` / `varchar`) — a real data
migration that requires:

1. Explicit sign-off (Aaron) on the canonical direction.
2. A schema-only + full backup of the affected table on the node, taken first.
3. Application **out-of-band** (manual `psql`, niced), bigboy/scratch first, then
   the live node, with row-count + feature verification between.

When a change here is signed off and applied, also flip the corresponding
`signoff` flag in `../canonical_schema.json` to the agreed `class` (drop the
`signoff` key) so the drift-check goes green for that column.

Tracked targets (see the schema-drift audit, 2026-06-13) — ALL SIGNED OFF + APPLIED:
- `D001` `credit_packages.id`        commander `integer` → `uuid`   (4 rows, no FK deps) — APPLIED 2026-06-13, backed up first
- `D002` `user_credits.user_id`      bigboy `uuid` → `varchar`      (1 row)  — APPLIED 2026-06-13, dropped local-users FK (was ON DELETE CASCADE)
- `D003` `user_provider_keys.user_id` bigboy `uuid` → `varchar`     (0 rows) — APPLIED 2026-06-13, dropped local-users FK

Their `signoff` flags are cleared from `../canonical_schema.json`; the drift-check now
treats the canonical types (uuid / varchar / varchar) as plain requirements, so a FUTURE
node that diverges trips a loud ERROR and an operator re-applies the matching D00x here.
A deployment that wants the local-users FK back: see `OVERLAY_local_user_integrity.md`.
