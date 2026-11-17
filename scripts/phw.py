#!/usr/bin/env python3
"""photowright CLI entry point. The code lives in the phw/ package next to this file:
core (batch 1 edits, recipes, rungs), masks (select, mask, cutout), compose (blend modes,
layers), layered (OpenRaster and PSD open/save). Run: python phw.py --help
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from phw import cli  # noqa: E402

if __name__ == "__main__":
    cli()
