"""Verify an archive: hashes, a full restore into a throw-away SQLite database, counts, views."""

from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text

from victus.backup.manifest import ManifestError
from victus.backup.restore import RestoreError, check_member_hashes, read_manifest, restore_backup
from victus.infrastructure.db.engine import make_engine
from victus.infrastructure.db.views import VIEW_NAMES


@dataclass(slots=True)
class VerifyResult:
    archive: Path
    ok: bool
    problems: list[str] = field(default_factory=list)
    tables: dict[str, int] = field(default_factory=dict)
    views: dict[str, int] = field(default_factory=dict)
    scope: str = "?"
    created_at: str = "?"

    def summary(self) -> str:
        state = "OK" if self.ok else "FAILED"
        head = f"{self.archive.name}: {state} (scope {self.scope}, created {self.created_at})"
        if self.problems:
            return head + "\n  - " + "\n  - ".join(self.problems)
        return head


def verify_backup(zip_path: Path) -> VerifyResult:
    """Return ``VerifyResult.ok`` if the archive is internally consistent and restorable."""
    result = VerifyResult(archive=zip_path, ok=False)
    if not zip_path.is_file():
        result.problems.append("file not found")
        return result
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad is not None:
                result.problems.append(f"corrupt zip member {bad}")
                return result
            manifest = read_manifest(zf)
            result.scope = manifest.scope_label
            result.created_at = manifest.created_at.isoformat()
            result.problems.extend(check_member_hashes(zf, manifest))
            if result.problems:
                return result
    except (zipfile.BadZipFile, ManifestError) as exc:
        result.problems.append(str(exc))
        return result

    with tempfile.TemporaryDirectory(prefix="victus-verify-") as tmp:
        db = Path(tmp) / "verify.db"
        engine = make_engine(f"sqlite:///{db.as_posix()}")
        try:
            restored = restore_backup(
                zip_path, engine, mode="fail_if_exists", dry_run=False, check_hashes=False
            )
            result.tables = dict(restored.counts_after)
            with engine.connect() as conn:
                for view in VIEW_NAMES:
                    result.views[view] = int(
                        conn.execute(text(f"SELECT count(*) FROM {view}")).scalar_one()
                    )
                conn.execute(text("PRAGMA foreign_key_check"))
                fk_problems = conn.execute(text("PRAGMA foreign_key_check")).all()
                if fk_problems:
                    result.problems.append(f"{len(fk_problems)} foreign key violation(s)")
        except RestoreError as exc:
            result.problems.append(str(exc))
        except Exception as exc:
            result.problems.append(f"{type(exc).__name__}: {exc}")
        finally:
            engine.dispose()

    result.ok = not result.problems
    return result


__all__ = ["VerifyResult", "verify_backup"]
