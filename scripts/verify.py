#!/usr/bin/env python3
"""Run all verification gates locally."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_ROOT_FILES = {
    ".env.example",
    ".gitattributes",
    ".gitignore",
    ".python-version",
    "README.md",
    "openapi.json",
    "pyproject.toml",
    "uv.lock",
}

ALLOWED_PREFIXES = (
    ".github/",
    ".githooks/",
    "backend/",
    "docker/",
    "docs/",
    "packages/",
    "scripts/",
    "test-console/",
)


def _run_step(name: str, cmd: list[str], cwd: Path = REPO_ROOT) -> None:
    print(f"==> [verify] {name}...")
    res = subprocess.run(cmd, cwd=cwd)
    if res.returncode != 0:
        print(f"FAILED: {name} exited with code {res.returncode}", file=sys.stderr)
        sys.exit(res.returncode)


def _check_tracked_files() -> None:
    print("==> [verify] Checking tracked files allowlist...")
    res = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    for path in res.stdout.splitlines():
        path = path.strip().replace("\\", "/")
        if not path:
            continue
        if path in ALLOWED_ROOT_FILES:
            continue
        if any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            continue
        print(f"FAILED: Tracked file {path!r} not in allowlist", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    py = sys.executable

    _run_step("Ruff check", [py, "-m", "ruff", "check", "."])
    _run_step("Ruff format", [py, "-m", "ruff", "format", "--check", "."])
    _run_step(
        "Mypy",
        [
            py,
            "-m",
            "mypy",
            "backend/src",
            "packages/shared/src",
            "backend/alembic",
            "scripts",
            "backend/tests",
        ],
    )
    _run_step("OpenAPI sync", [py, "scripts/export_openapi.py", "--check"])
    _run_step("Alembic check", [py, "-m", "alembic", "check"], cwd=REPO_ROOT / "backend")
    _check_tracked_files()
    _run_step("Pytest", [py, "-m", "pytest", "backend/tests", "-v"])

    print("\nAll verification gates passed successfully.")


if __name__ == "__main__":
    main()
