# Mela MCP

An agent-first, read-only MCP server for the locally synced Mela recipe library
on macOS. Direct Python access, deterministic JSON, no mela-cli runtime dependency.
Forked from [krumme/mela-mcp](https://github.com/krumme/mela-mcp), with selected
access/discovery/image logic adapted from [waynevernon/mela-cli](https://github.com/waynevernon/mela-cli).

The [source comparison and decisions](docs/architecture-comparison.md) explain
what was retained, adopted, and improved. [Validation](docs/validation.md) records
the tested behavior and current live-access limitation.

Unofficial third-party software; no affiliation with Mela or its developers.
Mela exposes no official database API, so storage/schema changes may require a
localized reader repair.

## Safety and scope

Mela is strictly read-only. The source database and existing WAL are opened only
as files for reading. A before/after identity, size, and timestamp check creates a
stable private temporary copy; SQLite operates on that copy with `mode=ro`,
`query_only=ON`, and an SQL authorizer denying writes/ATTACH/schema changes.
SQLite's own SHM bookkeeping stays in the temporary directory. Source copying is
retried at most three times, then returns `database_busy`. Nonempty rollback
journals are rejected. Snapshots are deleted when the connection closes.

There is no meal history, planning, pantry, shopping list, Calendar, Reminders,
or Mela import/write tool. Future history and inventory must live in databases
or files owned by this system. Recipe `uuid` (Mela's raw `ZID`) is the intended
reference for that state; local numeric `id` values can change if Mela rebuilds
its store. ZID persistence across Mela migrations is not guaranteed by an
external API, so future history needs reconciliation when a reference vanishes.

Ingredients and quantities, yield, times, instructions, notes, description,
nutrition, links and tags are returned as stored. Yield is a raw string, not an
inferred serving count; quantities and times are not parsed or normalized.

## Install and run

Python 3.10+ is required; live Mela discovery requires macOS.

```sh
git clone https://github.com/claessee/mela-mcp.git
cd mela-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m mela_mcp.diagnostics
```

Configure an MCP host to launch the stdio server using an absolute Python path:

```json
{
  "mcpServers": {
    "mela": {
      "command": "/absolute/path/to/mela-mcp/.venv/bin/python",
      "args": ["-m", "mela_mcp.server"]
    }
  }
}
```

The server entry point is also `.venv/bin/mela-mcp`. The diagnostic entry point
is `.venv/bin/mela-mcp-doctor`; it prints JSON and exits 0 for a readable compatible
catalog, 1 otherwise. No diagnostic text is printed on the stdio server channel.

## Configuration and discovery

| Variable | Purpose |
| --- | --- |
| `MELA_DB_PATH` | Authoritative explicit SQLite path. Also works for offline fixtures. |
| `MELA_APP_PATH` | Optional app bundle location when discovering the store. Bundle ID must be `recipes.mela.appkit`. |
| `MELA_SUPPORT_DIR` | Optional external-image directory; otherwise `.Curcuma_SUPPORT/_EXTERNAL_DATA` beside the selected database. |
| `MELA_COMPRESSION_TOOL` | Optional LZFSE decoder executable for the image helper; default `compression_tool`. Recipe tools do not need it. |

Without a DB override: inspect `/Applications/Mela.app` and `~/Applications/Mela.app`,
then Spotlight, verify the bundle ID, read codesign application-group entitlements,
and derive `Data/Curcuma.sqlite`. Fallback scans only Mela-named Group Containers.
Multiple candidate stores return `database_ambiguous`; choose with `MELA_DB_PATH`.
An explicit DB path bypasses app discovery and controls the default image path.

macOS may require permission to read another app's container. Diagnose the actual
error first and grant access to the process/MCP host if required. Permission,
missing database, incompatible schema, and optional missing image storage are
reported separately; the reader does not work around access denial.

## Tools

All results contain the same compact JSON in MCP text and `structuredContent`.
All tools advertise read-only, non-destructive, local access annotations. There
are no images/base64 or automatic recipe cards on the agent path.

| Tool | Arguments | Result |
| --- | --- | --- |
| `search_recipes` | `query`, optional `tag`, `favorite`, `want_to_cook`, `limit=20`, `offset=0` | Paginated summaries plus bounded snippets. All query words must match the same recipe across seven text fields. Literal substring matching with Unicode case folding. |
| `get_recipe` | `recipe_id`: integer local PK or exact string ZID | Complete raw recipe fields, flags, tags, date and image count. No fuzzy/prefix/title selection. |
| `list_tags` | None | Tags with distinct existing recipe counts; duplicate tag names grouped. |
| `list_recipes` | Optional exact `tag`, tri-state flags, `limit=20`, `offset=0` | Compact catalog summaries with IDs, states, tags, raw times/yield. |
| `list_favorites` | Optional `tag`, `limit=20`, `offset=0` | Same list contract, filtered to favorites. |
| `list_want_to_cook` | Optional `tag`, `limit=20`, `offset=0` | Same list contract, filtered to want-to-cook. |
| `diagnose_library` | None | Path provenance, access method, schema inventory/fingerprint, tag join mapping, SQLite quick-check, counts, warnings/errors. No recipe content. |

Pagination uses `limit` 1..100 and nonnegative `offset`. Follow `next_offset` until
null. Total/order/tag reads in one call use the same snapshot. Order is
case-folded title, raw title, then numeric ID. Separate calls take fresh snapshots;
a Mela sync between pages may move records, so a complete weekly scan should
check totals and deduplicate by ZID/ID. No claim of a persistent multi-call snapshot.

Tag filters match exact stored names. Boolean null/omitted means all, true means
flagged, false means unflagged; NULL stored flags are treated as false. A string
`"12"` is a ZID, while integer `12` is a PK. Duplicate ZIDs produce
`recipe_ambiguous`, allowing explicit numeric selection.

Example list response:

```json
{
  "ok": true,
  "recipes": [{
    "id": 12, "uuid": "recipe-id-from-mela", "title": "Lemon chicken",
    "favorite": true, "want_to_cook": false,
    "prep_time": "10 min", "cook_time": "40 min", "total_time": "50 min",
    "yield": "4", "tags": ["Dinner"]
  }],
  "total": 1, "limit": 20, "offset": 0, "next_offset": null,
  "schema_warnings": []
}
```

`get_recipe` returns `{ok:true,recipe:{...},schema_warnings:[]}`. Full recipe fields:
`id`, `uuid`, `title`, `ingredients`, `instructions`, `notes`, `description`,
`nutrition`, `link`, `prep_time`, `cook_time`, `total_time`, `yield`, `favorite`,
`want_to_cook`, `date_added`, `tags`, `image_count`. Optional unavailable
images/date return null with warnings, rather than a false zero or missing data.

Catalog failures return MCP `isError=true` and
`{ok:false,error:{code,message,details}}`. Codes include `database_missing`,
`database_ambiguous`, `access_denied`, `database_busy`, `database_invalid`,
`database_unreadable`, `schema_unsupported`, `invalid_argument`, `data_invalid`,
`recipe_not_found`, and `recipe_ambiguous`. Diagnostics return a full report with
an `errors` array. Input-type validation can also be rejected by the MCP SDK.

## Architecture and repair

- `discovery.py`: bounded app/entitlement/container discovery and path provenance.
- `snapshot.py`: source-file stability checks and private temporary snapshots.
- `schema.py`: required field mappings, inspected numbered tag relationship and fingerprint.
- `db.py`: read-only connection, raw extraction, filtering, pagination, batched tags.
- `diagnostics.py`: doctor checks independent of MCP.
- `images.py`: optional inline/raw/external/LZFSE/keyed-archive decoding with path/size guards.
- `server.py`: thin MCP wrappers and JSON/error envelopes; no SQL.

Unknown essential fields or ambiguous relationships fail closed. A changed
Core Data entity number is handled by inspecting join-table and column names,
not by assuming `Z_4TAGS`. Arbitrarily renamed entities/fields require evidence
and a change in `schema.py`, with a matching fixture. New extra columns are
reported in diagnostics without affecting known reads. Neither upstream has a
schema-version compatibility guarantee.

The upstream icon/image-conversion helpers and recipe-card asset remain in the
source tree for potential later presentation work; they are not imported or
registered by this agent server. Optional blob failures do not affect recipe
text reads. The LZFSE/archive helper is fixture-tested, not verified against an
installed Mela store here.

## Tests and licensing

```sh
.venv/bin/python -m pytest -q
MELA_LIVE_TEST=1 .venv/bin/python -m pytest tests/test_live.py -q -rs
```

Normal tests use generated fixtures, never real recipes. Coverage includes
read-only SQL enforcement, unchanged source files and WAL/SHM, committed WAL
visibility, discovery/access errors, schema drift, exact IDs/ambiguity, stable
pagination, Unicode/literal search, raw text, image guards, SDK dispatch, and an
actual stdio client/server workflow. Live tests are opt-in and explicitly skip
when no local store is found.

MIT. Original [LICENSE](LICENSE), adapted CLI [MIT notice](licenses/mela-cli-MIT.txt),
and [attribution](THIRD_PARTY_NOTICES.md) are preserved and packaged.
