"""Batch runner — process multiple raw dataset directories in one go."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .preprocessor import BasePreprocessor
from .types import BatchResult


class BatchRunner:
    """Registry + runner for dataset preprocessors."""

    def __init__(self, preprocessors: list[BasePreprocessor] | None = None) -> None:
        self._registry: dict[str, BasePreprocessor] = {}
        for p in (preprocessors or []):
            self.register(p)

    def register(self, preprocessor: BasePreprocessor) -> None:
        """Register a preprocessor by its ``dataset_type``."""
        self._registry[preprocessor.dataset_type] = preprocessor

    def get(self, dataset_type: str) -> BasePreprocessor:
        """Retrieve a registered preprocessor."""
        if dataset_type not in self._registry:
            available = ", ".join(sorted(self._registry)) or "(none)"
            raise KeyError(
                f"No preprocessor registered for type '{dataset_type}'. "
                f"Available: {available}"
            )
        return self._registry[dataset_type]

    @property
    def registered_types(self) -> list[str]:
        return sorted(self._registry)

    def run(
        self,
        specs: list[dict[str, Any]],
        *,
        overwrite: bool = False,
    ) -> list[BatchResult]:
        """Process multiple datasets.

        Each item in *specs* must have:
        - ``type``: registered dataset type (e.g. ``"xbow"``)
        - ``raw_path``: path to raw dataset directory
        - ``output_dir``: path to output dataset directory
        - ``dataset_id`` (optional): override the dataset suite id
        """
        results: list[BatchResult] = []
        for spec in specs:
            dtype = spec["type"]
            raw_path = Path(spec["raw_path"])
            output_dir = Path(spec["output_dir"])
            dataset_id = spec.get("dataset_id")

            preprocessor = self.get(dtype)
            result = preprocessor.process_batch(
                raw_path, output_dir,
                dataset_id=dataset_id, overwrite=overwrite,
            )
            results.append(result)
        return results
