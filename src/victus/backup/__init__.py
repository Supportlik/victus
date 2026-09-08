"""Backup: export, verify, restore, retention and scheduling (ADR 0008).

An archive is a ZIP with ``manifest.json``, one ``data/<table>.jsonl`` per
table, attachments under ``blobs/<sha256>`` and an optional SQLite snapshot
(``snapshot/victus.db``). Everything is plain text or hash-named files, so a
backup can be inspected with ``unzip -p`` and ``jq`` without Victus.

Public surface:

* :func:`victus.backup.export.create_backup`
* :func:`victus.backup.verify.verify_backup`
* :func:`victus.backup.restore.restore_backup`
* :func:`victus.backup.retention.apply_retention`
* :func:`victus.backup.schedule.run_backup_job` / :func:`victus.backup.schedule.run_scheduled`
"""

from victus.backup.export import BackupArchive, create_backup, list_archives
from victus.backup.manifest import Manifest
from victus.backup.restore import RestoreError, RestoreResult, restore_backup
from victus.backup.retention import apply_retention
from victus.backup.verify import VerifyResult, verify_backup

__all__ = [
    "BackupArchive",
    "Manifest",
    "RestoreError",
    "RestoreResult",
    "VerifyResult",
    "apply_retention",
    "create_backup",
    "list_archives",
    "restore_backup",
    "verify_backup",
]
