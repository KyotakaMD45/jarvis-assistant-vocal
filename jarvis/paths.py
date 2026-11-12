"""Central file locations. Everything lives next to the project root."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"
LOG_PATH = ROOT / "jarvis.log"
