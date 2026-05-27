"""
Model Registry — Versioned Model Storage
==========================================

Production model management for ARVIS ML components.

Provides:
- Versioned model save/load (pickle, joblib, keras)
- Metadata tracking (training metrics, feature names, timestamps)
- Active version management (symlink-style pointer)
- Auto-retrain trigger checking
"""

import json
import logging
import os
import pickle
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.ml.registry")

DEFAULT_MODELS_DIR = Path(__file__).parent.parent.parent / "data" / "models"


class ModelRegistry:
    """
    Versioned model storage with metadata tracking.

    Usage:
        registry = ModelRegistry()
        registry.save_model("energy_forecaster", model, {"rmse": 12.3, "mape": 0.08})
        model, metadata = registry.load_model("energy_forecaster")
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or DEFAULT_MODELS_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _model_dir(self, name: str) -> Path:
        return self.base_dir / name

    def _version_dir(self, name: str, version: str) -> Path:
        return self._model_dir(name) / version

    def _active_file(self, name: str) -> Path:
        return self._model_dir(name) / "active.txt"

    def save_model(
        self,
        name: str,
        model: Any,
        metrics: Dict[str, Any],
        version: Optional[str] = None,
        extra_artifacts: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Save a model with versioning and metadata.

        Args:
            name: Model identifier (e.g., "energy_forecaster")
            model: The model object (must be picklable)
            metrics: Training/validation metrics
            version: Version string (auto-generated if None)
            extra_artifacts: Additional objects to save (scalers, feature lists, etc.)

        Returns:
            Version string of the saved model
        """
        if version is None:
            version = f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        version_path = self._version_dir(name, version)
        version_path.mkdir(parents=True, exist_ok=True)

        model_path = version_path / "model.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(model, f)

        if extra_artifacts:
            for artifact_name, artifact in extra_artifacts.items():
                artifact_path = version_path / f"{artifact_name}.pkl"
                with open(artifact_path, "wb") as f:
                    pickle.dump(artifact, f)

        metadata = {
            "name": name,
            "version": version,
            "created_at": datetime.now().isoformat(),
            "metrics": metrics,
            "artifacts": list((extra_artifacts or {}).keys()),
            "model_file": "model.pkl",
        }
        metadata_path = version_path / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        self._set_active(name, version)
        logger.info(f"Model saved: {name}/{version} (metrics: {metrics})")
        return version

    def load_model(
        self, name: str, version: Optional[str] = None
    ) -> Tuple[Optional[Any], Dict[str, Any]]:
        """
        Load a model and its metadata.

        Args:
            name: Model identifier
            version: Specific version to load (defaults to active)

        Returns:
            (model, metadata) tuple. Model is None if not found.
        """
        if version is None:
            version = self.get_active_version(name)

        if version is None:
            logger.warning(f"No model found for: {name}")
            return None, {}

        version_path = self._version_dir(name, version)
        model_path = version_path / "model.pkl"
        metadata_path = version_path / "metadata.json"

        if not model_path.exists():
            logger.warning(f"Model file not found: {model_path}")
            return None, {}

        with open(model_path, "rb") as f:
            model = pickle.load(f)

        metadata = {}
        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)

        logger.info(f"Model loaded: {name}/{version}")
        return model, metadata

    def load_artifact(self, name: str, artifact_name: str, version: Optional[str] = None) -> Optional[Any]:
        """Load an extra artifact (scaler, feature list, etc.)."""
        if version is None:
            version = self.get_active_version(name)
        if version is None:
            return None

        artifact_path = self._version_dir(name, version) / f"{artifact_name}.pkl"
        if not artifact_path.exists():
            return None

        with open(artifact_path, "rb") as f:
            return pickle.load(f)

    def get_active_version(self, name: str) -> Optional[str]:
        """Get the currently active version for a model."""
        active_file = self._active_file(name)
        if active_file.exists():
            return active_file.read_text().strip()
        return None

    def _set_active(self, name: str, version: str):
        """Set the active version pointer."""
        model_dir = self._model_dir(name)
        model_dir.mkdir(parents=True, exist_ok=True)
        active_file = self._active_file(name)
        active_file.write_text(version)

    def list_versions(self, name: str) -> List[Dict[str, Any]]:
        """List all versions of a model with their metadata."""
        model_dir = self._model_dir(name)
        if not model_dir.exists():
            return []

        versions = []
        active = self.get_active_version(name)

        for entry in sorted(model_dir.iterdir()):
            if entry.is_dir() and entry.name.startswith("v"):
                metadata_path = entry / "metadata.json"
                meta = {}
                if metadata_path.exists():
                    with open(metadata_path) as f:
                        meta = json.load(f)
                versions.append({
                    "version": entry.name,
                    "is_active": entry.name == active,
                    "created_at": meta.get("created_at", "unknown"),
                    "metrics": meta.get("metrics", {}),
                })

        return versions

    def delete_version(self, name: str, version: str) -> bool:
        """Delete a specific model version. Cannot delete active version."""
        if version == self.get_active_version(name):
            logger.warning(f"Cannot delete active version: {name}/{version}")
            return False

        version_path = self._version_dir(name, version)
        if version_path.exists():
            shutil.rmtree(version_path)
            logger.info(f"Deleted model version: {name}/{version}")
            return True
        return False

    def cleanup_old_versions(self, name: str, keep: int = 3):
        """Keep only the N most recent versions (plus active)."""
        versions = self.list_versions(name)
        active = self.get_active_version(name)

        non_active = [v for v in versions if v["version"] != active]
        non_active.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        for v in non_active[keep:]:
            self.delete_version(name, v["version"])


_registry_instance = None


def get_model_registry() -> ModelRegistry:
    """Get singleton model registry instance."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ModelRegistry()
    return _registry_instance
