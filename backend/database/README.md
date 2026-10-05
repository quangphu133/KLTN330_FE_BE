# Anonymized PostgreSQL snapshot

These SQL files contain a sanitized structural and metrics snapshot of the configured PostgreSQL database. The schema reflects the source catalog. The data keeps selected operational counts, relationships, durations, scores, deductions, and known categorical values while replacing identifiers and personal or free-text content.

This is not a complete application clone or an AI/audio demonstration. It contains no audio bytes, transcripts, analysis JSON, client numbers, detected keywords, snippets, original file paths, job identifiers, notification text, source password hashes, or working credentials. Historic scores and deductions are preserved as recorded; they are not recalculated or verified against audio. Dates are synthetic row-order anchors and cannot be used for real calendar analysis. These transformations reduce exposure but do not guarantee irreversible anonymity.

Only these categorical domains are carried through: user role (`admin`, `telesales`), ASR job status (`queued`, `running`, `completed`, `failed`), sentiment (`positive`, `neutral`, `negative`), violation severity (`low`, `medium`, `high`), violation type (`missing_greeting`, `missing_closing`, `sensitive_keyword`, `forced_selling`, `abusive_language`, `negative_attitude`), vocabulary type (`All`, `OnlyOperator`, `OnlyClient`, `Hotwords`), and notification event type (`completed`, `needs_confirmation`, `insufficient_speakers`, `failed`). Unknown or free-text category values become `NULL` where allowed, or the literal `sanitized` where the column is required. Colors are retained only when they match `#RRGGBB` or `#RRGGBBAA`; other values become `NULL`. All JSON columns are `NULL`. Entity names use `Sanitized Project N`, `Sanitized Checklist N`, and `Sanitized Vocabulary N`; people use `Demo User N` and `userNNNN@example.com`. Job and event keys use `SANITIZED-JOB-NNNNNN` and `SANITIZED-EVENT-NNNNNN`. Audio paths use `[audio omitted - no media exported]`; notification titles and messages use fixed sanitized text.

## Restore

Use a new, dedicated PostgreSQL database named `kltn330_anonymized`. Both SQL files enforce that exact database name and reject a different target. Do not use a live or existing application database. `createdb` must fail if that name already exists; do not drop or empty an existing database to make room.

From the repository root, create the database and apply the files in order:

```powershell
createdb kltn330_anonymized
psql -v ON_ERROR_STOP=1 -d kltn330_anonymized -f backend/database/schema.sql
psql -v ON_ERROR_STOP=1 -d kltn330_anonymized -f backend/database/data_anonymized.sql
```

The schema stops before creating tables if the `public` schema already has a table. The data script checks that all expected tables exist and that every public table is empty before inserting; both scripts run in transactions so an error prevents a partial restore. Use a separate local connection setting if you later point an application at this database.

All restored users are inactive. Their hashes are fresh bcrypt hashes of unpublished throwaway secrets, and no password is provided. The bundled accounts cannot log in. The application creates users through its admin-only user endpoint; this snapshot does not add an account bootstrap mechanism. Use an independently configured admin provisioning procedure only if your deployment already has one.

The export preserves referential relationships through consistently remapped IDs and reseeds the serial sequences. Schema and row counts were taken from one read-only snapshot of the source database; data values were transformed in memory before being written to this file.
