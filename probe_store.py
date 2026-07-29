"""Checks the archive store is reachable and writable before a run costs anything.

    ./venv/bin/python probe_store.py

Reads R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY. These
are the *data* bucket credentials and are deliberately separate from the
AWS_-prefixed Terraform state credentials -- confusing the two is the most
common cause of an AccessDenied here.
"""

import logging
import os
import sys

from dotenv import load_dotenv

from pylitical.store import StoreError, make_store


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    load_dotenv()

    print("configuration:")
    for name in (
        "R2_ACCOUNT_ID",
        "R2_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    ):
        value = os.environ.get(name, "")
        shown = f"set ({len(value)} chars)" if value else "MISSING"
        if name == "R2_BUCKET" and value:
            shown = value
        print(f"  {name:24} {shown}")
    print()

    try:
        store = make_store("r2")
        store.verify()
    except StoreError as exc:
        print(f"FAILED: {exc}\n")
        return 1

    print("Store is reachable and writable. Safe to run the pipeline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
