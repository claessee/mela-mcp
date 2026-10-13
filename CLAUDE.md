# mela-mcp

An unofficial, read-only MCP server that exposes recipes from the Mela macOS app
to MCP-compatible assistants. See README.md for the seven structured tools.

## Conventions

- Schema assumptions live in `schema.py`, queries in `db.py`, discovery in
  `discovery.py`, optional blob decoding in `images.py`. No SQL in server.py.
- Mela is strictly read-only. Source DB/WAL files are copied with stability
  checks into an owned temporary snapshot; SQLite never opens the Mela source.
- Future meal history, plans, pantry and inventory must live in system-owned
  files/databases. Do not add any Mela import or write surface.
- Requires `mcp>=2.0` (`MCPServer`); the older `FastMCP` API is gone.
- Run tests with `python -m pytest`. The live test (`tests/test_live.py`) needs Mela
  installed; explicitly enable with MELA_LIVE_TEST=1. Missing live storage must
  be reported as a verification limitation, never as a fixture-based success.
