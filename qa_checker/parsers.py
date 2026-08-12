from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any, BinaryIO, Iterator

import ijson

from qa_checker.models import ProjectType


def iter_tasks(stream: BinaryIO) -> Iterator[dict[str, Any]]:
    """Stream tasks from a top-level Label Studio JSON array."""
    yield from ijson.items(stream, "item", use_float=True)


def open_task_stream(path: str | Path) -> BinaryIO:
    resolved = Path(path).expanduser()
    if resolved.name.lower().endswith(".json.gz"):
        return gzip.open(resolved, "rb")
    return resolved.open("rb")


def uploaded_task_stream(stream: BinaryIO, filename: str) -> BinaryIO:
    stream.seek(0)
    if filename.lower().endswith(".json.gz"):
        return gzip.GzipFile(fileobj=stream, mode="rb")
    return stream


def is_supported_filename(filename: str) -> bool:
    lowered = filename.lower()
    return lowered.endswith(".json") or lowered.endswith(".json.gz")


def resolve_local_path(raw_path: str) -> Path:
    """Resolve an exact path, with a cautious fallback for whitespace-only name differences."""
    path = Path(raw_path).expanduser()
    if path.is_file():
        return path
    if not path.is_absolute():
        return path

    current = Path(path.anchor)
    for part in path.parts[1:]:
        exact = current / part
        if exact.exists():
            current = exact
            continue
        if not current.is_dir():
            return path
        matches = [
            child
            for child in current.iterdir()
            if child.name.strip() == part.strip()
        ]
        if len(matches) != 1:
            return path
        current = matches[0]
    return current


def latest_annotation(task: dict[str, Any]) -> dict[str, Any] | None:
    annotations = [
        item
        for item in task.get("annotations", [])
        if isinstance(item, dict) and not item.get("was_cancelled", False)
    ]
    if not annotations:
        return None
    return max(
        annotations,
        key=lambda item: (
            str(item.get("updated_at") or item.get("created_at") or ""),
            int(item.get("id") or 0),
        ),
    )


def latest_reviewer_action(task: dict[str, Any]) -> str | None:
    """Return the latest final reviewer action without retaining reviewer identity."""
    reviewed_annotations: list[tuple[dict[str, Any], str]] = []
    for item in task.get("annotations", []):
        if not isinstance(item, dict):
            continue
        action = str(item.get("last_action") or "").strip().lower()
        if action not in {"accepted", "fixed_and_accepted", "rejected"}:
            if item.get("accepted") is True:
                action = "accepted"
            else:
                continue
        reviewed_annotations.append((item, action))

    if not reviewed_annotations:
        return None
    _, action = max(
        reviewed_annotations,
        key=lambda pair: (
            str(pair[0].get("updated_at") or pair[0].get("created_at") or ""),
            int(pair[0].get("id") or 0),
        ),
    )
    return action


def annotation_results(task: dict[str, Any]) -> list[dict[str, Any]]:
    annotation = latest_annotation(task)
    if annotation is None:
        return []
    results = annotation.get("result", [])
    return [item for item in results if isinstance(item, dict)]


def detect_project_type(task: dict[str, Any]) -> ProjectType:
    result_types = {str(item.get("type", "")).lower() for item in annotation_results(task)}
    data_keys = {str(key).lower() for key in task.get("data", {})}

    if "videorectangle" in result_types or any(
        key.startswith("video_url") for key in data_keys
    ):
        return "omnitrack"
    if "rectanglelabels" in result_types or any(
        key.startswith(("image", "imga", "imgb")) for key in data_keys
    ):
        return "multiview"
    raise ValueError(
        "无法识别项目类型：未找到 videorectangle、rectanglelabels 或视频/图片字段。"
    )
