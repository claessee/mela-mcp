# Mela read layer: comparison and first-version decision

Compared before implementation on 2026-10-13:

- [krumme/mela-mcp](https://github.com/krumme/mela-mcp), commit `751ce33735f1ce12248c0ae4757890c57bac729c`.
- [waynevernon/mela-cli](https://github.com/waynevernon/mela-cli), commit `a3a60629908394e29aba026a62e40df59cfbf95b` (1.0.1).

Both source trees, database/access modules, discovery, server/CLI entry points, fixtures, and tests were inspected. Krumme's unchanged baseline passed 54 tests with 3 skips on this Mac.

| Area | Krumme MCP | mela-cli | First-version decision |
| --- | --- | --- | --- |
| Architecture | SQL isolated in `db.py`; MCP and recipe-card presentation in `server.py` | Discovery separate from a direct Python `MelaStore`; CLI/export formatting separate | Retain the MCP package, SDK, stdio entry point, and direct Python access. Separate discovery, schema, database reads, and optional image decoding. No CLI dependency. |
| App/container discovery | One hard-coded Group Container, DB override | App bundle validation, Spotlight, codesign entitlements, container scan, explicit path provenance | Adapt CLI discovery. Bound subprocess timeouts; reject multiple candidate stores instead of picking the first; derive external-data path from the selected DB. |
| SQLite safety | URI `mode=ro`, but falls back to `immutable=1` | Escaped URI and `mode=ro`, no immutable fallback | Retain escaped read-only SQLite access; add query-only and an SQL authorizer. Read source files into a private temporary snapshot first so SQLite cannot create or modify Mela WAL/SHM files. Reject a source that changes during copying. Never open the live source with SQLite or use immutable against it. |
| Diagnostics | Missing-path exception | Doctor reports paths, discovery sources, capabilities, count | Adopt doctor concept. Add schema inventory/fingerprint, required-field checks, relationship mapping, access errors and catalog counts. Image support is optional, not a condition for a healthy recipe catalog. |
| Schema resilience | Hard-coded tables/fields and `Z_4TAGS` / `Z_4RECIPES` / `Z_5TAGS` | Same hard-coded schema | Neither is sufficient. Inspect actual tables/columns; discover the numbered recipe/tag join by shape; reject missing or ambiguous essential mappings. Missing optional dates/images produce warnings/nulls, not invented data. Keep all schema assumptions in `schema.py`. |
| Recipe fields | Full raw text, times, yield, states, local PK and ZID | Same raw fields; richer list summaries | Keep raw fields exactly as stored. Adopt useful summary fields (ZID, states, times, yield). No inferred servings, duration parsing, or ingredient normalization. |
| Search | All words must match across seven text columns; literal wildcard escaping | Single substring, unescaped LIKE patterns | Retain Krumme's all-word and literal-pattern semantics. Add Unicode case folding and deterministic ID tie-breaks. |
| Tags | Exact tag filter, counts and per-recipe reads | Multiple tags, grouped summaries, case-insensitive filtering | Preserve exact tag filtering. Batch tag reads for each result page; distinct counts exclude dangling relationships. |
| Favorites/want-to-cook | Tri-state filters | True-only CLI switches and summary booleans | Retain tri-state filtering. Add explicit list wrappers sharing one query path; these avoid empty-search workarounds and make agent intent clear. NULL flags mean false. |
| IDs/selectors | Local numeric PK only; UUID in details | PK, exact ZID/title, ID prefixes, fuzzy title; ambiguity errors | Return both numeric `id` and raw `uuid` (ZID). Accept only typed numeric PK or exact string ZID. No heuristic title/prefix selection. ZID is the intended future history key, subject to Mela preserving it. |
| Images/external blobs | Inline bytes and UUID external files; size/traversal guard; sips converter | Raw images, external references, LZFSE and NSKeyedArchiver `CD_data` extraction | Adapt CLI image detection/archive logic, retain and strengthen MCP size/path guards. Optional helper only; recipe tools return image metadata/counts, never decode images or include base64. Compressed images must not break recipe reads. |
| Errors/tests | Pytest fixtures; read-only, wildcard, image safety, live tests; extensive widget tests | Unittest discovery/store/selector/CLI fixtures | Retain useful data/safety fixtures. Add access/schema/ambiguity/pagination/Unicode/SQL-denial/source-immutability/WAL/structured-MCP tests. Replace presentation-specific server tests with agent-interface tests. |
| Agent interface | Search/tag arrays; full details primarily Markdown; structured payload shaped for widget | Rich JSON/CSV but CLI-oriented | Consistent JSON results, paging metadata, structured error codes, read-only annotations; no automatic UI/image processing. |

## Scope and safety

Tools: `search_recipes`, `get_recipe`, `list_tags`, `list_recipes`, `list_favorites`, `list_want_to_cook`, `diagnose_library`.

SQLite's ordinary read-only WAL access can still use shared-memory bookkeeping. To satisfy the stricter source-file boundary, copy only the selected database and its existing WAL to a system-owned temporary directory with before/after file identity checks and bounded retries. SQLite reads that stable private copy using `mode=ro` and can create its own SHM there. A nonempty rollback journal is rejected rather than recovered in Mela's directory. Snapshot size/copy cost is the deliberate first-version tradeoff; no persistent caching or daemon is introduced. Each tool call has one database snapshot; separate pages can reflect later Mela syncs.

No history, plans, pantry, shopping, Calendar, Reminders, Mela import, or Mela write API is added. Future state must use a separate system-owned store and reference recipe ZIDs. There is no second access implementation and no mela-cli subprocess invocation. Optional system tools (`mdfind`, `codesign`, `compression_tool`) perform discovery/image decoding only.

The original Krumme MIT license remains. Adapted mela-cli discovery/image logic retains its upstream MIT text in `licenses/mela-cli-MIT.txt` and attribution in source/`THIRD_PARTY_NOTICES.md`.

## Local evidence before implementation

Mela was not found in `/Applications`, `~/Applications`, or Spotlight using its correct `recipes.mela.appkit` bundle ID. No matching Mela Group Container was found; the old fixed `Curcuma.sqlite` path does not exist. The provided iCloud `Mela` folder is empty. Checks outside the sandbox gave the same result. Therefore no current local schema or real recipe data is available to inspect; implementation must not claim live verification. Diagnostics and opt-in live tests will report this explicitly.
