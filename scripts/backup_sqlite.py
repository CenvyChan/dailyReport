"""SQLite 在线备份。用 sqlite3 的 backup API，不直接复制正在使用的库文件。

用法：
    python scripts/backup_sqlite.py                    # 落到 settings.BACKUP_DIRECTORY
    python scripts/backup_sqlite.py --target D:\\bak    # 指定目录
    python scripts/backup_sqlite.py --keep 14          # 只保留最近 14 份
"""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.db import connection


PREFIX = "daily-report-"
SUFFIX = ".sqlite3"
DEFAULT_KEEP = 30


def backup_database(target: Path, *, keep: int = DEFAULT_KEEP) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    output = target / f"{PREFIX}{datetime.now():%Y%m%d-%H%M%S}{SUFFIX}"
    connection.ensure_connection()
    source = connection.connection
    destination = sqlite3.connect(output)
    with destination:
        source.backup(destination)
    try:
        _verify(destination)
    finally:
        destination.close()
    _prune(target, keep)
    return output


def _verify(destination) -> None:
    """备份完立刻校验。一份损坏的备份比没有备份更危险——真要恢复时才发现就晚了。"""
    result = destination.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"备份文件校验失败：{result[0] if result else '无返回'}")


def _prune(target: Path, keep: int) -> list[Path]:
    """按文件名（含时间戳）倒序保留最近 keep 份，其余删掉。
    不做轮转的话备份目录会一直涨，磁盘满了连数据库都写不进去。"""
    if keep <= 0:
        return []
    backups = sorted(target.glob(f"{PREFIX}*{SUFFIX}"), reverse=True)
    stale = backups[keep:]
    for path in stale:
        path.unlink()
    return stale


if __name__ == "__main__":
    import argparse
    import django

    django.setup()
    from django.conf import settings

    parser = argparse.ArgumentParser(description="备份 SQLite 数据库并轮转旧备份")
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="备份目录，默认取 settings.BACKUP_DIRECTORY",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_KEEP,
        help=f"保留最近几份备份，默认 {DEFAULT_KEEP}；传 0 表示不清理",
    )
    args = parser.parse_args()
    destination = args.target or Path(settings.BACKUP_DIRECTORY)
    print(backup_database(destination, keep=args.keep))
