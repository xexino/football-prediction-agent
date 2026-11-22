"""Online SQLite backups (consistent while the app is running) with rotation, and restore."""
from __future__ import annotations

import gzip
import shutil
import sqlite3
from pathlib import Path

from .config import settings
from .timeutil import utcnow

KEEP = 14


def backup(dest_dir: Path | None = None) -> Path:
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
    for old in sorted(dest_dir.glob("fil-*.db.gz"))[:-KEEP]:
        old.unlink()
    return out


def restore(path: Path) -> None:
    """Restore a backup over the configured DB (stop the server first)."""
    path = Path(path)
    target = Path(settings.db_path)
    if target.exists():
        shutil.copy2(target, target.with_suffix(f".before-restore-{utcnow():%Y%m%dT%H%M%S}.db"))
    for suffix in ("-wal", "-shm"):
        p = Path(str(target) + suffix)
        if p.exists():
            p.unlink()
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f, open(target, "wb") as g:
        shutil.copyfileobj(f, g)
