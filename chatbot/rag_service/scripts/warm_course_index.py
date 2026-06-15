#!/usr/bin/env python3
"""Pre-warm Chroma index for one or more Moodle courses (cron-friendly).

Usage:
  python scripts/warm_course_index.py 4 5 6
  python scripts/warm_course_index.py --all-enrolled --user-id 3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import settings
from infrastructure.moodle_db import list_enrolled_course_ids
from services.index_service import warm_course_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Warm Moodle course vector index")
    parser.add_argument("course_ids", nargs="*", type=int, help="Moodle course ids")
    parser.add_argument("--all-enrolled", action="store_true")
    parser.add_argument("--user-id", type=int, default=0)
    args = parser.parse_args()

    ids: list[int] = list(args.course_ids)
    if args.all_enrolled:
        uid = int(args.user_id)
        if uid <= 1:
            print("error: --user-id required with --all-enrolled", file=sys.stderr)
            sys.exit(1)
        limit = int(getattr(settings, "cross_course_search_max", 12) or 12)
        ids = list_enrolled_course_ids(settings, uid, limit=limit * 2)[:limit]

    if not ids:
        print("error: provide course_ids or --all-enrolled", file=sys.stderr)
        sys.exit(1)

    for cid in ids:
        try:
            name = warm_course_index(cid, sync=True)
            print(f"ok course_id={cid} ({name})")
        except Exception as e:
            print(f"fail course_id={cid}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
