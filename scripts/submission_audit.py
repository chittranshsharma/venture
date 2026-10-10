"""Inspect attempts, revoke a reservation, or make a consistent SQLite backup."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Show attempts for a specific job URL")
    parser.add_argument("--backup", metavar="PATH", help="Create a new SQLite backup; never overwrite a file")
    parser.add_argument("--abort-reservation", metavar="TOKEN",
                        help="Stop an active reservation. A started submission is quarantined as unverified.")
    args = parser.parse_args()
    from core import db_manager as db
    if args.backup:
        db.backup_database(args.backup)
        print(f"Backup saved: {Path(args.backup).resolve()}")
    if args.abort_reservation:
        db.finish_submission(args.abort_reservation, "aborted", "Reservation revoked by operator via audit command.")
        print("Reservation stopped. Review the portal if submission had already started.")
    print(json.dumps({"checked_at": datetime.now().isoformat(),
                      "daily_slots_used": db.get_daily_apply_count(),
                      "attempts": db.get_submission_attempts(args.url)}, indent=2))


if __name__ == "__main__":
    main()
