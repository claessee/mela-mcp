"""Agent-facing MCP tools. All Mela knowledge and reads live in the access layer."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Callable

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import StrictBool, StrictInt, StrictStr

from . import db, diagnostics
from .errors import MelaError, error_dict

mcp = MCPServer("mela")
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=False)


def _result(payload: dict, *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False,
                                                                         separators=(",", ":"), allow_nan=False))],
                          structured_content=payload, is_error=is_error)


def _read(operation: Callable) -> CallToolResult:
    try:
        with closing(db.connect()) as conn:
            return _result({"ok": True, **operation(conn)})
    except (MelaError, OSError, sqlite3.DatabaseError) as exc:
        return _result({"ok": False, "error": error_dict(exc)}, is_error=True)


@mcp.tool(annotations=READ_ONLY)
def get_recipe(recipe_id: StrictInt | StrictStr) -> CallToolResult:
    """Read full raw recipe data. Integer recipe_id selects local id/PK; string
    selects exact uuid/ZID returned by list/search. No title or prefix matching.
    Returns {ok, recipe, schema_warnings}, or {ok:false,error:{code,message,details}}.
    Ingredients/quantities, yield and times are exactly as stored, not normalized.
    Images are counted only; no image decoding or base64 enters agent context.
    """
    def load(conn):
        recipe = db.get_recipe(conn, recipe_id)
        if recipe is None:
            raise MelaError("recipe_not_found", "No recipe with that exact id.", recipe_id=recipe_id)
        return {"recipe": recipe, "schema_warnings": conn.schema.warnings}
    return _read(load)


@mcp.tool(annotations=READ_ONLY)
def search_recipes(query: StrictStr, tag: StrictStr | None = None,
                   favorite: StrictBool | None = None, want_to_cook: StrictBool | None = None,
                   limit: StrictInt = 20, offset: StrictInt = 0) -> CallToolResult:
    """Case-insensitive literal substring search across title, ingredients,
    instructions, notes, description, nutrition and link. ALL words must match
    the same recipe. Optional exact tag and tri-state boolean filters (null=all).
    Returns {ok,recipes,total,limit,offset,next_offset,schema_warnings}; summaries
    include id, uuid, states, tags, raw times/yield and a 120-character snippet.
    limit is 1..100. Order is case-folded title, raw title, numeric id. Follow
    next_offset until null. Each call reads a fresh local snapshot.
    """
    return _read(lambda conn: db.recipe_page(conn, query, tag, favorite, want_to_cook,
                                            limit, offset, snippets=True))


@mcp.tool(annotations=READ_ONLY)
def list_recipes(tag: StrictStr | None = None, favorite: StrictBool | None = None,
                 want_to_cook: StrictBool | None = None, limit: StrictInt = 20,
                 offset: StrictInt = 0) -> CallToolResult:
    """Browse compact recipe summaries without text search. Exact tag and
    tri-state boolean filters; same pagination/order as search_recipes. Returns
    {ok,recipes,total,limit,offset,next_offset,schema_warnings}. Fetch full raw
    ingredients and instructions with get_recipe. No image loading.
    """
    return _read(lambda conn: db.recipe_page(conn, tag=tag, favorite=favorite,
                                            want_to_cook=want_to_cook, limit=limit, offset=offset))


@mcp.tool(annotations=READ_ONLY)
def list_favorites(tag: StrictStr | None = None, limit: StrictInt = 20, offset: StrictInt = 0) -> CallToolResult:
    """List only favorites, with optional exact tag. Same compact summaries and
    paging envelope as list_recipes; follow next_offset until null.
    """
    return list_recipes(tag=tag, favorite=True, limit=limit, offset=offset)


@mcp.tool(annotations=READ_ONLY)
def list_want_to_cook(tag: StrictStr | None = None, limit: StrictInt = 20, offset: StrictInt = 0) -> CallToolResult:
    """List only recipes marked want-to-cook, with optional exact tag. Same
    compact summaries and paging envelope as list_recipes.
    """
    return list_recipes(tag=tag, want_to_cook=True, limit=limit, offset=offset)


@mcp.tool(annotations=READ_ONLY)
def list_tags() -> CallToolResult:
    """Return {ok,tags:[{tag,count}]}. Counts are distinct existing recipes;
    duplicate names are grouped. Order: count descending, case-folded/raw name.
    """
    return _read(lambda conn: {"tags": db.list_tags(conn)})


@mcp.tool(annotations=READ_ONLY)
def diagnose_library() -> CallToolResult:
    """Check discovery, read access, SQLite integrity, schema fields and tag
    relationships. Returns ok, path provenance, schema fingerprint/inventory,
    counts, warnings and errors; no recipe content. Use first when reads fail.
    Missing image support does not make the text catalog unhealthy.
    """
    report = diagnostics.diagnose_library()
    return _result(report, is_error=not report["ok"])


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
