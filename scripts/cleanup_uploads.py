#!/usr/bin/env python
"""清理过期上传文件。

用法（cron 或手动）:
    python scripts/cleanup_uploads.py
    python scripts/cleanup_uploads.py --days 5

典型 crontab 条目（每天凌晨 3 点执行）:
    0 3 * * * cd /app && python scripts/cleanup_uploads.py \
        >> /var/log/upload_cleanup.log 2>&1
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from common.storage import LocalStorage

from backend.globals import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="清理过期上传文件")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="保留天数（默认读取 settings.upload_retain_days）",
    )
    args = parser.parse_args()

    days = args.days if args.days is not None else settings.upload_retain_days
    storage = LocalStorage(settings.upload_dir)
    removed = storage.cleanup(retain_days=days)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{ts}] cleanup done: removed {removed} expired directories")


if __name__ == "__main__":
    sys.exit(main() or 0)
