from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def load_profile_config() -> dict[str, Any]:
    """Load manual profile settings relative to the project, regardless of cwd."""
    with (ROOT / "profile.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)
