"""Read-only Mela catalog API. No MCP imports, source writes, or planning state."""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .discovery import discover_mela
from .errors import MelaError
from .schema import FIELDS, SEARCH_FIELDS, Schema, inspect_schema, quote_identifier
from .snapshot import copy_snapshot

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_PAGE_SIZE = 100
DEFAULT_DB_PATH = "~/Library/Group Containers/66JC38RDUD.recipes.mela/Data/Curcuma.sqlite"


class Connection(sqlite3.Connection):
    schema: Schema

    def close(self) -> None:
        try:
            super().close()
        finally:
            directory = getattr(self, "snapshot_directory", None)
            if directory is not None:
                directory.cleanup()
                self.snapshot_directory = None


def get_db_path() -> str:
    discovery = discover_mela()
    if discovery.errors:
        error = discovery.errors[0]
        raise MelaError(error["code"], error["message"], discovery=discovery.to_dict())
    if discovery.db_path is None:
        raise FileNotFoundError("Mela database not found. Set MELA_DB_PATH or install Mela and sync recipes locally.")
    try:
        discovery.db_path.stat()  # Preserve access errors instead of disguising them as missing files.
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Mela database not found at '{discovery.db_path}'. Set MELA_DB_PATH or sync Mela locally.") from exc
    return str(discovery.db_path)


def _authorize(action, arg1, arg2, database, trigger):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                  sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and (
        (arg1 == "table_info") or
        (arg1 in {"query_only", "database_list", "schema_version", "user_version", "quick_check"} and arg2 is None)
    ):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connect(path: str | Path | None = None) -> Connection:
    source = Path(path if path is not None else get_db_path()).expanduser().resolve()
    directory, snapshot = copy_snapshot(source)
    conn = None
    try:
        conn = sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True,
                               timeout=2, factory=Connection)
        conn.snapshot_directory = directory
        conn.source_path = source
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.create_function("mela_contains", 2,
                             lambda value, term: int(term.casefold() in str(value or "").casefold()),
                             deterministic=True)
        conn.create_collation("MELA_CASEFOLD", lambda a, b:
                              (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
        conn.set_authorizer(_authorize)
        conn.execute("BEGIN")
        conn.schema = inspect_schema(conn)
        return conn
    except BaseException:
        if conn is not None:
            conn.close()
        else:
            directory.cleanup()
        raise


def _schema(conn: Connection) -> Schema:
    conn.schema.require_valid()
    return conn.schema


def _coredata_ts_to_iso(ts):
    if ts is None:
        return None
    try:
        value = float(ts)
        if not math.isfinite(value):
            raise ValueError("non-finite date")
        return datetime.fromtimestamp(value + 978307200, tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        raise MelaError("data_invalid", "Recipe date is not a supported Core Data timestamp.") from exc


def _recipe_fields(row: sqlite3.Row, schema: Schema, fields: list[str]) -> dict:
    result = {key: row[FIELDS[key]] if FIELDS[key] in schema.tables["ZRECIPEOBJECT"] else None
              for key in fields}
    if not isinstance(result.get("id"), int) or result["id"] <= 0:
        raise MelaError("data_invalid", "Recipe primary key is not a positive integer.")
    for key, value in result.items():
        if key not in {"id", "favorite", "want_to_cook", "date_added"} and value is not None and not isinstance(value, str):
            raise MelaError("data_invalid", f"Recipe {key} is not text as expected by the inspected schema.")
    for key in ("favorite", "want_to_cook"):
        if key in result:
            if result[key] not in (0, 1, None):
                raise MelaError("data_invalid", f"Recipe {key} flag is not 0, 1, or NULL.")
            result[key] = bool(result[key])
    if "date_added" in result:
        result["date_added"] = _coredata_ts_to_iso(result["date_added"])
    return result


def _tags_batch(conn: Connection, ids: list[int]) -> dict[int, list[str]]:
    result = {pk: [] for pk in ids}
    if not ids:
        return result
    s = _schema(conn)
    join, recipe, tag = map(quote_identifier, (s.join_table, s.recipe_column, s.tag_column))
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT DISTINCT j.{recipe} AS id, t.ZTITLE AS tag FROM {join} j "
        f"JOIN ZRECIPETAG t ON t.Z_PK=j.{tag} WHERE j.{recipe} IN ({marks}) "
        "AND t.ZTITLE IS NOT NULL AND t.ZTITLE!='' "
        "ORDER BY t.ZTITLE COLLATE MELA_CASEFOLD, t.ZTITLE", ids)
    for row in rows:
        if not isinstance(row["tag"], str):
            raise MelaError("data_invalid", "Tag title is not text as expected by the inspected schema.")
        result[row["id"]].append(row["tag"])
    return result


def list_tags(conn: Connection) -> list[dict]:
    s = _schema(conn)
    join, recipe, tag = map(quote_identifier, (s.join_table, s.recipe_column, s.tag_column))
    rows = conn.execute(
        f"SELECT t.ZTITLE AS tag, COUNT(DISTINCT r.Z_PK) AS count FROM ZRECIPETAG t "
        f"LEFT JOIN {join} j ON j.{tag}=t.Z_PK "
        f"LEFT JOIN ZRECIPEOBJECT r ON r.Z_PK=j.{recipe} "
        "WHERE t.ZTITLE IS NOT NULL AND t.ZTITLE!='' GROUP BY t.ZTITLE "
        "ORDER BY count DESC, tag COLLATE MELA_CASEFOLD, tag")
    result = [dict(row) for row in rows]
    if any(not isinstance(row["tag"], str) for row in result):
        raise MelaError("data_invalid", "Tag title is not text as expected by the inspected schema.")
    return result


def image_count(conn: Connection, pk: int) -> int | None:
    if not _schema(conn).images:
        return None
    return conn.execute("SELECT COUNT(*) FROM ZRECIPEIMAGEOBJECT WHERE ZRECIPE=?", (pk,)).fetchone()[0]


def get_recipe(conn: Connection, pk: int | str) -> dict | None:
    """Numeric values select local PK; strings select exact ZID. Never guess."""
    s = _schema(conn)
    if isinstance(pk, bool) or not isinstance(pk, (int, str)) or (isinstance(pk, int) and pk <= 0) or pk == "":
        raise MelaError("invalid_argument", "recipe_id must be a positive integer PK or a nonempty exact ZID string.")
    column = "Z_PK" if isinstance(pk, int) else "ZID"
    rows = conn.execute(f"SELECT * FROM ZRECIPEOBJECT WHERE {column}=? ORDER BY Z_PK LIMIT 2", (pk,)).fetchall()
    if len(rows) > 1:
        raise MelaError("recipe_ambiguous", "Multiple recipes have that ZID; use a numeric id.", recipe_id=pk)
    if not rows:
        return None
    result = _recipe_fields(rows[0], s, list(FIELDS))
    result["tags"] = _tags_batch(conn, [result["id"]])[result["id"]]
    result["image_count"] = image_count(conn, result["id"])
    return result


def _validate_page(limit: int, offset: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_SIZE:
        raise MelaError("invalid_argument", f"limit must be an integer from 1 to {MAX_PAGE_SIZE}.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise MelaError("invalid_argument", "offset must be a nonnegative integer.")


def recipe_page(conn: Connection, query: str = "", tag: str | None = None,
                favorite: bool | None = None, want_to_cook: bool | None = None,
                limit: int = 20, offset: int = 0, *, snippets: bool = False) -> dict:
    _validate_page(limit, offset)
    s = _schema(conn)
    if not isinstance(query, str) or len(query) > 2000 or len(query.split()) > 32:
        raise MelaError("invalid_argument", "query must be text, at most 2000 characters and 32 words.")
    if tag is not None and not isinstance(tag, str):
        raise MelaError("invalid_argument", "tag must be an exact tag name or null.")
    for name, value in (("favorite", favorite), ("want_to_cook", want_to_cook)):
        if value is not None and not isinstance(value, bool):
            raise MelaError("invalid_argument", f"{name} must be true, false, or null.")
    terms = query.split()
    where, params = [], []
    for term in terms:
        where.append("(" + " OR ".join(f"mela_contains(r.{FIELDS[c]}, ?)" for c in SEARCH_FIELDS) + ")")
        params.extend([term] * len(SEARCH_FIELDS))
    for key, value in (("favorite", favorite), ("want_to_cook", want_to_cook)):
        if value is not None:
            where.append(f"COALESCE(r.{FIELDS[key]},0)=?")
            params.append(int(value))
    if tag is not None:
        join, recipe, tag_col = map(quote_identifier, (s.join_table, s.recipe_column, s.tag_column))
        where.append(f"EXISTS (SELECT 1 FROM {join} j JOIN ZRECIPETAG t ON t.Z_PK=j.{tag_col} "
                     f"WHERE j.{recipe}=r.Z_PK AND t.ZTITLE=?)")
        params.append(tag)
    clause = " AND ".join(where) if where else "1"
    total = conn.execute(f"SELECT COUNT(*) FROM ZRECIPEOBJECT r WHERE {clause}", params).fetchone()[0]
    fields = ["id", "uuid", "title", "favorite", "want_to_cook", "prep_time", "cook_time", "total_time", "yield"]
    selected = list(dict.fromkeys([FIELDS[c] for c in fields] + ([FIELDS[c] for c in SEARCH_FIELDS] if snippets else [])))
    rows = conn.execute("SELECT " + ", ".join("r." + c for c in selected) +
                        f" FROM ZRECIPEOBJECT r WHERE {clause} "
                        "ORDER BY r.ZTITLE COLLATE MELA_CASEFOLD, r.ZTITLE, r.Z_PK LIMIT ? OFFSET ?",
                        params + [limit, offset]).fetchall()
    tags = _tags_batch(conn, [r["Z_PK"] for r in rows])
    results = []
    for row in rows:
        result = _recipe_fields(row, s, fields)
        result["tags"] = tags[result["id"]]
        if snippets:
            text = " ".join(str(row[FIELDS[c]] or "") for c in SEARCH_FIELDS)
            result["snippet"] = text[:120]  # Bounded preview; full raw text is in get_recipe.
        results.append(result)
    next_offset = offset + len(results)
    return {"recipes": results, "total": total, "limit": limit, "offset": offset,
            "next_offset": next_offset if next_offset < total else None,
            "schema_warnings": s.warnings}


def search_recipes(conn, query, tag=None, favorite=None, want_to_cook=None, limit=20, offset=0):
    """Compatibility helper; the MCP uses recipe_page for paging metadata."""
    return recipe_page(conn, query, tag, favorite, want_to_cook, limit, offset, snippets=True)["recipes"]


def get_recipe_image_bytes(conn: Connection, db_path: str, pk: int, index: int = 0) -> bytes | None:
    """Optional image helper; never called by recipe MCP tools."""
    if index < 0 or not _schema(conn).images:
        return None
    row = conn.execute("SELECT ZDATA FROM ZRECIPEIMAGEOBJECT WHERE ZRECIPE=? "
                       "ORDER BY ZINDEX, Z_PK LIMIT 1 OFFSET ?", (pk, index)).fetchone()
    if row is None:
        return None
    from .images import decode_image
    import os
    support = os.environ.get("MELA_SUPPORT_DIR") or str(Path(db_path).parent / ".Curcuma_SUPPORT/_EXTERNAL_DATA")
    try:
        return decode_image(row[0], Path(support).expanduser(), max_bytes=MAX_IMAGE_BYTES)
    except MelaError:
        return None  # Optional legacy helper; detailed decoder exceptions remain available.
