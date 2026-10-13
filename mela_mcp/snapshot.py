"""Stable private DB/WAL copy. The Mela source is only opened with file mode rb."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .errors import MelaError


def _fingerprint(path: Path) -> tuple | None:
    try:
        s = path.stat()
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
    except FileNotFoundError:
        return None


def copy_snapshot(source: Path) -> tuple[tempfile.TemporaryDirectory, Path]:
    """Reject concurrent writes/checkpoints; bounded retries, no source SQLite calls.

    SQLite creates WAL shared memory only in our temporary directory. Copying
    SHM would incorrectly preserve another process's locks, so never copy it.
    """
    wal = Path(str(source) + "-wal")
    journal = Path(str(source) + "-journal")
    for _ in range(3):
        before = [_fingerprint(p) for p in (source, wal, journal)]
        if before[0] is None:
            raise FileNotFoundError(f"Mela database not found at '{source}'. Set MELA_DB_PATH or sync Mela locally.")
        if before[2] and before[2][2] > 0:
            raise MelaError("database_busy", "A rollback journal is present; wait for Mela to finish writing.")
        directory = tempfile.TemporaryDirectory(prefix="mela-mcp-")
        target = Path(directory.name) / "Curcuma.sqlite"
        try:
            shutil.copyfile(source, target)
            if before[1] is not None:
                shutil.copyfile(wal, Path(str(target) + "-wal"))
            after = [_fingerprint(p) for p in (source, wal, journal)]
            if before == after:
                return directory, target
        except FileNotFoundError:
            # A concurrent WAL reset/replacement is handled by the next attempt.
            pass
        except BaseException:
            directory.cleanup()
            raise
        directory.cleanup()
    raise MelaError("database_busy", "Mela's database changed during all three snapshot attempts; retry later.")
