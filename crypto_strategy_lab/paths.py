"""Stable application paths independent of the current working directory."""
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "Config"
OUTPUT_DIR = PROJECT_ROOT / "output"
