"""Generate clearly labelled synthetic navigation fixtures for research E2E.

The output is NOT real environmental data.  Every field is marked
``quality: synthetic`` in navigation_manifest.json and must be used with
``dataPolicy=allow_synthetic_research``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "tests"))

from navigation_fixtures import full_fixture_tree  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT / "sample-data" / "navigation",
        help="Output fixture root (default: sample-data/navigation)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    full_fixture_tree(root)
    files = sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file())
    print(f"Synthetic navigation fixtures written to {root}")
    for path in files:
        print(f"  {path}")
    print("Use NAVIGATION_DATA_ROOT=<root>, NAVIGATION_ICE_DATA_ROOT=<root>/ice,")
    print("NAVIGATION_ICE_BACKEND=nextsim, dataPolicy=allow_synthetic_research.")


if __name__ == "__main__":
    main()
