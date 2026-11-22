"""Online SQLite backups (consistent while the app is running) with rotation, and restore."""
from __future__ import annotations

import gzip
import shutil
import sqlite3
from pathlib import Path

from .config import settings
from .timeutil import utcnow

KEEP = 14


def verify_backup(path: Path) -> dict:
    """Restore the backup into a temporary file and run the integrity checks on it."""
    import tempfile

    from .integrity import check_database

    with tempfile.TemporaryDirectory() as td:
        tmpdb = Path(td) / "verify.db"
        with gzip.open(path, "rb") as f, open(tmpdb, "wb") as g:
            shutil.copyfileobj(f, g)
        return check_database(tmpdb)


def backup(dest_dir: Path | None = None, verify: bool = False) -> Path:
    dest_dir = Path(dest_dir or settings.backup_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    tmp = dest_dir / f"fil-{stamp}.db"
    src = sqlite3.connect(settings.db_path)
    dst = sqlite3.connect(tmp)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    out = tmp.with_suffix(".db.gz")
    with open(tmp, "rb") as f, gzip.open(out, "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g)
    tmp.unlink()
    if verify:
        res = verify_backup(out)
        if not res["ok"]:
            out.rename(out.with_suffix(".corrupt"))
            raise RuntimeError(f"backup verification failed: {res['problems']}")
    for old in sorted(dest_dir.glob("fil-*.db.gz"))[:-KEEP]:
        old.unlink()
    return out


def restore(path: Path) -> None:
    """Restore a backup over the configured DB (stop the server first)."""
    path = Path(path)
    target = Path(settings.db_path)
    from . import db as dbmod

    if dbmod._engine is not None:  # release open connections/WAL before replacing the file
        dbmod._engine.dispose()
    if target.exists():
        shutil.copy2(target, target.with_suffix(f".before-restore-{utcnow():%Y%m%dT%H%M%S}.db"))
    for suffix in ("-wal", "-shm"):
        p = Path(str(target) + suffix)
        if p.exists():
            p.unlink()
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f, open(target, "wb") as g:
        shutil.copyfileobj(f, g)
    from .integrity import check_database

    res = check_database(target)
    if not res["ok"]:
        raise RuntimeError(f"restored database failed integrity checks: {res['problems']}")
