#!/usr/bin/env python3
"""Export curated dashboard demo JSON used by the API and README screenshots."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weather_copy_bot.demo_data import export_demo_json  # noqa: E402


def main() -> None:
    path = export_demo_json()
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
