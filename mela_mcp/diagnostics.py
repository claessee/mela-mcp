"""Doctor-style checks without importing the MCP SDK or touching recipe content."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing

from . import db
from .discovery import discover_mela
from .errors import MelaError, error_dict


def diagnose_library() -> dict:
    discovery = discover_mela()
    report = {"ok": False, "discovery": discovery.to_dict(), "read_only": True,
              "access_method": "stable_private_snapshot", "schema": None, "counts": None,
              "warnings": list(discovery.warnings), "errors": list(discovery.errors)}
    if discovery.errors:
        return report
    if discovery.db_path is None:
        report["errors"].append({"code": "database_missing", "message": "No local Mela store found. Set MELA_DB_PATH or install and sync Mela.", "details": {}})
        return report
    try:
        with closing(db.connect(discovery.db_path)) as conn:
            report["schema"] = conn.schema.to_dict()
            report["warnings"].extend(conn.schema.warnings)
            conn.schema.require_valid()
            check = conn.execute("PRAGMA quick_check").fetchall()
            if [r[0] for r in check] != ["ok"]:
                raise MelaError("database_invalid", "SQLite quick_check failed.", results=[r[0] for r in check])
            row = conn.execute("SELECT COUNT(*) AS recipes, "
                               "SUM(COALESCE(ZFAVORITE,0)=1) AS favorites, "
                               "SUM(COALESCE(ZWANTTOCOOK,0)=1) AS want_to_cook "
                               "FROM ZRECIPEOBJECT").fetchone()
            report["counts"] = {key: row[key] or 0 for key in row.keys()}
            report["counts"]["tags"] = len(db.list_tags(conn))
            duplicates = conn.execute("SELECT COUNT(*) FROM (SELECT ZID FROM ZRECIPEOBJECT "
                                      "WHERE ZID IS NOT NULL GROUP BY ZID HAVING COUNT(*)>1)").fetchone()[0]
            if duplicates:
                report["warnings"].append(f"{duplicates} duplicate ZIDs; use numeric ids for those recipes.")
            if not discovery.support_dir.is_dir():
                report["warnings"].append("External image directory is unavailable; recipe text remains readable.")
            report["ok"] = True
    except (MelaError, OSError, sqlite3.DatabaseError) as exc:
        report["errors"].append(error_dict(exc))
    return report


def main() -> None:
    report = diagnose_library()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
