import sqlite3
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.db import connection


def backup_database(target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    output = target / f"daily-report-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    connection.ensure_connection()
    source = connection.connection
    destination = sqlite3.connect(output)
    with destination:
        source.backup(destination)
    destination.close()
    return output


if __name__ == "__main__":
    import argparse
    import django

    django.setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()
    print(backup_database(args.target))
