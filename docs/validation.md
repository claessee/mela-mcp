# Validation evidence

2026-10-13, macOS / Python 3.14, MCP SDK and mcp-types 2.3.0.

- Upstream baseline before changes: **54 passed, 3 skipped**.
- Fork suite after changes: **96 passed, 2 skipped**. Skips are the opt-in live catalog test and upstream installed-app icon test; Mela is not installed in the discovered locations.
- Real stdio server/client workflow: initialized the separate server process, listed tools, retrieved favorites, selected a full recipe by exact ZID, checked a structured missing-recipe error, and called diagnostics. This uses generated fixture recipes, not a live Mela library.
- Source immutability: byte hashes and modification timestamps stay unchanged after reads. A separate WAL test keeps a writer open, commits an uncheckpointed change, confirms that the reader sees it, and checks identical source DB/WAL/SHM bytes and timestamps afterward.
- SQL defenses: UPDATE, DELETE, CREATE (including TEMP), DROP, ATTACH, VACUUM, query-only disabling, journal-mode change, and WAL checkpoint attempts are rejected.
- Schema/access: numbered tag relationship changes, ambiguous relationships, missing essential fields, unavailable optional image/date schema, invalid SQLite files, permission failures, changing snapshot sources, rollback journals, and unusual path characters are covered.
- Catalog behavior: raw recipe fields, tri-state flags including NULL, all-word literal Unicode search, exact IDs, duplicate-ID errors, deterministic tie breaks, page metadata, batched tags, and duplicate/dangling tag relationships are covered.
- Optional images: raw/inline/external data, keyed archives, malformed references/UIDs, traversal/symlink/size guards, compressed-data decoder orchestration, and decoder absence are fixture-tested. Real Mela compressed assets remain unverified.
- Packaging: the 0.2.0 wheel builds; original Krumme license and full mela-cli MIT notice/attribution are included. No database or recipe data is packaged.

## Live verification limitation

Checks inside and outside the sandbox found no Mela app in `/Applications`,
`~/Applications`, or Spotlight (`recipes.mela.appkit`), no matching Mela Group
Container, and no database at the original fixed path. The supplied iCloud
`Mela` directory is empty.

`MELA_LIVE_TEST=1 python -m pytest tests/test_live.py -q -rs` explicitly skipped
with “No local Mela installation/database was found; live verification
unavailable.” The outside-sandbox doctor returned `ok:false`,
`database_missing`, no schema and no catalog counts. Therefore neither actual
local schema compatibility nor real recipe extraction has been verified.

When the app/store is available, run the doctor and opt-in live test above.
Set `MELA_DB_PATH` if its location is outside discovery. A failure must be
investigated against the actual schema; do not loosen schema checks or use
an immutable live-store fallback to make the test pass.
