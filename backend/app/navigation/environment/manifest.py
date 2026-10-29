"""Optional data-root manifest: provenance and synthetic-data marking.

A real data root normally has no manifest.  Synthetic research fixtures must
ship one with ``quality: synthetic`` so the same files can never be mistaken
for real observations by ``real_only`` planning.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.navigation.contracts import DataQuality

MANIFEST_FILENAME = "navigation_manifest.json"


class ManifestField(BaseModel):
    model_config = ConfigDict(frozen=True)

    quality: DataQuality = DataQuality.REAL
    source: str | None = None
    glob: str | None = None
    units: dict[str, str] = Field(default_factory=dict)
    time_semantics: str | None = None


class EnvironmentManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int = 1
    fields: dict[str, ManifestField] = Field(default_factory=dict)

    def field(self, name: str) -> ManifestField:
        return self.fields.get(name, ManifestField())

    def quality(self, name: str) -> DataQuality:
        return self.field(name).quality

    def source(self, name: str, default: str | None = None) -> str | None:
        return self.field(name).source or default


class ManifestError(ValueError):
    """Raised when a manifest exists but cannot be parsed."""


def load_manifest(path: str | Path) -> EnvironmentManifest:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        return EnvironmentManifest()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        return EnvironmentManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ManifestError(f"Invalid navigation manifest {manifest_path}: {error}") from error


def manifest_files(root: str | Path, pattern: str | None) -> list[Path]:
    directory = Path(root)
    if pattern is None or not directory.is_dir():
        return []
    return sorted(directory.glob(pattern))
