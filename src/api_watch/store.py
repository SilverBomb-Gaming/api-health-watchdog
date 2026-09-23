"""Write the last run to a local JSON file."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_RESULTS_PATH = Path(".api-watch") / "last-results.json"


def save_results(path: Path, payload: dict[str, object]) -> None:
    """Replace the file with this run. The parent directory is created when needed."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
