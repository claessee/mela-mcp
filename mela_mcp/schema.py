"""The single location for Mela/Core Data schema assumptions."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass

from .errors import MelaError

FIELDS = {
    "id": "Z_PK", "uuid": "ZID", "title": "ZTITLE", "ingredients": "ZINGREDIENTS",
    "instructions": "ZINSTRUCTIONS", "notes": "ZNOTES", "description": "ZTEXT",
    "nutrition": "ZNUTRITION", "link": "ZLINK", "prep_time": "ZPREPTIME",
    "cook_time": "ZCOOKTIME", "total_time": "ZTOTALTIME", "yield": "ZYIELD",
    "favorite": "ZFAVORITE", "want_to_cook": "ZWANTTOCOOK", "date_added": "ZDATE",
}
SEARCH_FIELDS = ("title", "ingredients", "instructions", "notes", "description", "nutrition", "link")


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@dataclass
class Schema:
    tables: dict[str, list[str]]
    join_table: str | None
    recipe_column: str | None
    tag_column: str | None
    images: bool
    warnings: list[str]
    missing: list[str]
    fingerprint: str

    def require_valid(self) -> None:
        if self.missing:
            raise MelaError("schema_unsupported", "Mela schema is missing or has ambiguous required mappings. Run diagnose_library.",
                            missing=self.missing, fingerprint=self.fingerprint)

    def to_dict(self) -> dict:
        return {"compatible": not self.missing, "tables": self.tables,
                "tag_relationship": {"table": self.join_table, "recipe_column": self.recipe_column,
                                     "tag_column": self.tag_column},
                "images_available": self.images, "warnings": self.warnings,
                "missing": self.missing, "fingerprint": self.fingerprint}


def inspect_schema(conn: sqlite3.Connection) -> Schema:
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    tables = {name: sorted(r[1] for r in conn.execute(f"PRAGMA table_info({quote_identifier(name)})")) for name in names}
    required = {"ZRECIPEOBJECT": set(FIELDS.values()) - {"ZDATE"}, "ZRECIPETAG": {"Z_PK", "ZTITLE"}}
    missing = [f"{table}.{column}" for table, columns in required.items()
               for column in sorted(columns - set(tables.get(table, [])))]
    matches = []
    for table, columns in tables.items():
        if not re.fullmatch(r"Z_\d+TAGS", table):
            continue
        recipes = [c for c in columns if re.fullmatch(r"Z_\d+RECIPES", c)]
        tags = [c for c in columns if re.fullmatch(r"Z_\d+TAGS", c)]
        if len(recipes) == len(tags) == 1:
            matches.append((table, recipes[0], tags[0]))
    if len(matches) != 1:
        missing.append("unique recipe/tag join (Z_<entity>TAGS with recipe/tag columns)")
    join = matches[0] if len(matches) == 1 else (None, None, None)
    images = {"Z_PK", "ZRECIPE", "ZINDEX", "ZDATA"}.issubset(tables.get("ZRECIPEIMAGEOBJECT", []))
    warnings = []
    if "ZDATE" not in tables.get("ZRECIPEOBJECT", []):
        warnings.append("Optional recipe date is unavailable; date_added is null.")
    if not images:
        warnings.append("Optional image schema is unavailable; image_count is null.")
    fingerprint = hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    return Schema(tables, *join, images, warnings, missing, fingerprint)
