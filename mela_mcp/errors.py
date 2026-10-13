"""Stable access-layer errors, independent of the MCP SDK."""
import sqlite3


class MelaError(RuntimeError):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.details = details

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "details": self.details}


def error_dict(exc: Exception) -> dict:
    if isinstance(exc, MelaError):
        return exc.to_dict()
    if isinstance(exc, FileNotFoundError):
        code = "database_missing"
    elif isinstance(exc, PermissionError):
        code = "access_denied"
    elif isinstance(exc, sqlite3.DatabaseError):
        name = getattr(exc, "sqlite_errorname", "")
        code = ("database_busy" if name.startswith(("SQLITE_BUSY", "SQLITE_LOCKED")) else
                "database_invalid" if name.startswith(("SQLITE_CORRUPT", "SQLITE_NOTADB")) else
                "database_unreadable")
    else:
        code = "io_error"
    return {"code": code, "message": str(exc), "details": {}}
