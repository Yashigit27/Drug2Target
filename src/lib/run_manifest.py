from __future__ import annotations

import json
from pathlib import Path

from src.lib.models import Manifest


def write_manifest(path: Path, manifest: Manifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def read_manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))
