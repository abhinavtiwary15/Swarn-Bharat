#!/usr/bin/env python3
"""Export the FastAPI OpenAPI schema to openapi.json."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_PLACEHOLDERS: dict[str, str] = {
    "APP_ENV": "development",
    "DATABASE_URL": "postgresql+asyncpg://x:x@localhost:5432/x",
    "REDIS_BASE_URL": "redis://localhost:6379",
    "JWT_SECRET_KEY": "export-script-placeholder-secret-key-32b",
    "JWT_REFRESH_SECRET_KEY": "export-script-placeholder-refresh-32b",
}
for _k, _v in _PLACEHOLDERS.items():
    os.environ.setdefault(_k, _v)

from backend.main import app  # noqa: E402

_REPO_ROOT = Path(__file__).parent.parent
_OUTPUT = _REPO_ROOT / "openapi.json"


def _render() -> str:
    schema = app.openapi()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def _is_tracked() -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(_OUTPUT)],
        capture_output=True,
        cwd=_REPO_ROOT,
    )
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check existing openapi.json is up to date; exit 1 if not.",
    )
    args = parser.parse_args()

    if args.check:
        if not _OUTPUT.exists():
            print(f"ERROR: {_OUTPUT.name} does not exist.", file=sys.stderr)
            print("Run:  python scripts/export_openapi.py", file=sys.stderr)
            sys.exit(1)

        if not _is_tracked():
            print(
                f"ERROR: {_OUTPUT.name} is not tracked by git. Add and commit it first.",
                file=sys.stderr,
            )
            sys.exit(1)

        current = _render()
        committed = _OUTPUT.read_text(encoding="utf-8")
        if current != committed:
            print(f"ERROR: {_OUTPUT.name} is out of date. Run:", file=sys.stderr)
            print("  python scripts/export_openapi.py", file=sys.stderr)
            print("and commit the result.", file=sys.stderr)
            sys.exit(1)

        print(f"OK: {_OUTPUT.name} is up to date.")
    else:
        _OUTPUT.write_text(_render(), encoding="utf-8")
        print(f"Written: {_OUTPUT}")


if __name__ == "__main__":
    main()
