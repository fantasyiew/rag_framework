"""Persistent evaluation datasets with a portable JSON Lines representation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from time import time
from typing import Any

from pydantic import ValidationError

from .models import EvaluationCase, EvaluationDataset, EvaluationDatasetSummary


class DatasetFormatError(ValueError):
    """Raised when an imported JSONL dataset cannot be validated."""


class EvaluationDatasetStore:
    def __init__(self, directory: Path, *, max_cases: int = 10000) -> None:
        if max_cases < 1:
            raise ValueError("Evaluation dataset case limit must be positive")
        self.directory = directory
        self.max_cases = max_cases
        self.directory.mkdir(parents=True, exist_ok=True)

    def import_jsonl(
        self,
        content: str,
        *,
        name: str,
        description: str | None = None,
    ) -> EvaluationDataset:
        cases: list[EvaluationCase] = []
        for line_number, raw_line in enumerate(content.splitlines(), 1):
            line = raw_line.strip()
            if not line:
                continue
            if len(cases) >= self.max_cases:
                raise DatasetFormatError(
                    f"Dataset exceeds the maximum of {self.max_cases} cases"
                )
            cases.append(self._parse_case(line, line_number))
        if not cases:
            raise DatasetFormatError("Dataset contains no evaluation cases")
        try:
            dataset = EvaluationDataset(name=name, description=description, cases=cases)
        except ValidationError as exc:
            raise DatasetFormatError(_validation_message(exc)) from exc
        self.save(dataset)
        return dataset

    def save(self, dataset: EvaluationDataset) -> None:
        dataset.updated_at = time()
        path = self._path(dataset.id)
        temporary_path = path.with_suffix(".json.tmp")
        temporary_path.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
        temporary_path.replace(path)

    def get(self, dataset_id: str) -> EvaluationDataset | None:
        try:
            path = self._path(dataset_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        try:
            return EvaluationDataset.model_validate_json(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def list(self) -> list[EvaluationDatasetSummary]:
        datasets: list[EvaluationDataset] = []
        for path in self.directory.glob("*.json"):
            try:
                datasets.append(EvaluationDataset.model_validate_json(path.read_text("utf-8")))
            except (OSError, ValueError):
                continue
        return [
            EvaluationDatasetSummary(
                id=dataset.id,
                name=dataset.name,
                description=dataset.description,
                case_count=len(dataset.cases),
                created_at=dataset.created_at,
                updated_at=dataset.updated_at,
            )
            for dataset in sorted(datasets, key=lambda item: item.updated_at, reverse=True)
        ]

    def export_jsonl(self, dataset_id: str) -> str | None:
        dataset = self.get(dataset_id)
        if dataset is None:
            return None
        return "\n".join(case.model_dump_json(exclude_none=True) for case in dataset.cases) + "\n"

    @staticmethod
    def _parse_case(line: str, line_number: int) -> EvaluationCase:
        try:
            payload: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetFormatError(f"Line {line_number}: invalid JSON") from exc
        if not isinstance(payload, dict):
            raise DatasetFormatError(f"Line {line_number}: expected a JSON object")
        if isinstance(payload.get("query"), str):
            payload["query"] = {"text": payload["query"]}
        try:
            return EvaluationCase.model_validate(payload)
        except ValidationError as exc:
            raise DatasetFormatError(f"Line {line_number}: {_validation_message(exc)}") from exc

    def _path(self, dataset_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", dataset_id):
            raise ValueError("Invalid evaluation dataset id")
        return self.directory / f"{dataset_id}.json"


def _validation_message(exc: ValidationError) -> str:
    error = exc.errors(include_url=False)[0]
    location = ".".join(str(part) for part in error["loc"])
    return f"{location}: {error['msg']}" if location else str(error["msg"])
