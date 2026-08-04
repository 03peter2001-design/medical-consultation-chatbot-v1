"""Export or verify the committed OpenAPI contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.factory import app

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_DIR / "docs" / "openapi.json"


def rendered_openapi() -> str:
    return (
        json.dumps(
            app.openapi(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the committed contract differs from the application schema.",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    expected = rendered_openapi()

    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != expected:
            print(f"OpenAPI contract is stale: {output}")
            print("Run: cd backend && python -m scripts.export_openapi")
            return 1
        print(f"OpenAPI contract is current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8")
    print(f"Wrote OpenAPI contract: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
