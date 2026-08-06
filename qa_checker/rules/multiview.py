from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from qa_checker.models import Issue
from qa_checker.parsers import annotation_results, latest_annotation

ALLOWED_LABELS = {"item", "barcode"}
ALLOWED_BBOX_CHOICES = {"moving"}


def _issue(
    task_id: str,
    code: str,
    severity: str,
    zh: str,
    en: str,
    result: dict[str, Any] | None = None,
    **details: Any,
) -> Issue:
    return Issue(
        task_id=task_id,
        code=code,
        severity=severity,  # type: ignore[arg-type]
        message_zh=zh,
        message_en=en,
        result_id=str((result or {}).get("id", "")),
        details=details,
    )


def _check_geometry(task_id: str, result: dict[str, Any]) -> list[Issue]:
    value = result.get("value", {})
    try:
        x = float(value["x"])
        y = float(value["y"])
        width = float(value["width"])
        height = float(value["height"])
    except (KeyError, TypeError, ValueError):
        return [
            _issue(
                task_id,
                "MV_INVALID_GEOMETRY",
                "error",
                "bbox 缺少有效坐标。",
                "Bounding box is missing valid geometry.",
                result,
            )
        ]

    if (
        width <= 0
        or height <= 0
        or x < 0
        or y < 0
        or x + width > 100.5
        or y + height > 100.5
    ):
        return [
            _issue(
                task_id,
                "MV_OUT_OF_BOUNDS",
                "error",
                "bbox 为空或超出画面范围。",
                "Bounding box is empty or outside the image bounds.",
                result,
                x=x,
                y=y,
                width=width,
                height=height,
            )
        ]
    return []


def check_task(task: dict[str, Any]) -> tuple[list[Issue], Counter[str]]:
    task_id = str(task.get("id", "unknown"))
    issues: list[Issue] = []
    metrics: Counter[str] = Counter()

    if latest_annotation(task) is None:
        return [
            _issue(
                task_id,
                "MV_NO_ANNOTATION",
                "error",
                "任务没有有效标注。",
                "Task has no valid annotation.",
            )
        ], metrics

    data = task.get("data", {})
    image_fields = {
        str(key): str(value)
        for key, value in data.items()
        if value and ("image" in str(key).lower() or str(key).lower().startswith("img"))
    }
    if len(image_fields) < 2:
        issues.append(
            _issue(
                task_id,
                "MV_MISSING_VIEW",
                "error",
                "任务缺少至少一个相机画面。",
                "Task is missing at least one camera view.",
                views=len(image_fields),
            )
        )
    if len(set(image_fields.values())) != len(image_fields):
        issues.append(
            _issue(
                task_id,
                "MV_DUPLICATE_VIEW",
                "error",
                "不同相机字段引用了相同图片。",
                "Different camera fields reference the same image.",
            )
        )

    results = annotation_results(task)
    boxes: dict[str, dict[str, Any]] = {}
    labels_by_id: dict[str, str] = {}
    choices_by_id: defaultdict[str, list[str]] = defaultdict(list)
    choice_results: list[dict[str, Any]] = []
    relations: list[tuple[str, str]] = []

    for result in results:
        result_type = str(result.get("type", "")).lower()
        result_id = str(result.get("id", ""))
        value = result.get("value", {})

        if result_type == "rectanglelabels":
            labels = [str(label).strip().lower() for label in value.get("rectanglelabels", [])]
            label = labels[0] if labels else ""
            boxes[result_id] = result
            labels_by_id[result_id] = label
            metrics["bboxes"] += 1
            metrics[f"label_{label or 'missing'}"] += 1
            if len(labels) != 1 or label not in ALLOWED_LABELS:
                issues.append(
                    _issue(
                        task_id,
                        "MV_INVALID_LABEL",
                        "error",
                        "bbox 必须且只能使用 item 或 barcode 标签。",
                        "Bounding box must use exactly one item or barcode label.",
                        result,
                        labels="|".join(labels),
                    )
                )
            issues.extend(_check_geometry(task_id, result))
            if not result.get("to_name"):
                issues.append(
                    _issue(
                        task_id,
                        "MV_MISSING_CAMERA_TARGET",
                        "error",
                        "bbox 缺少相机目标字段 to_name。",
                        "Bounding box is missing the camera target field to_name.",
                        result,
                    )
                )

        elif result_type == "choices":
            choices = [str(choice).strip().lower() for choice in value.get("choices", [])]
            choices_by_id[result_id].extend(choices)
            choice_results.append(result)
            for choice in choices:
                if choice not in ALLOWED_BBOX_CHOICES:
                    issues.append(
                        _issue(
                            task_id,
                            "MV_INVALID_CHOICE",
                            "error",
                            "bbox 属性包含未知值。",
                            "Bounding-box attribute contains an unknown value.",
                            result,
                            choice=choice,
                        )
                    )

        elif result_type == "relation":
            relations.append((str(result.get("from_id", "")), str(result.get("to_id", ""))))

    if not boxes:
        issues.append(
            _issue(
                task_id,
                "MV_NO_BBOX",
                "warning",
                "任务中没有 bbox，请确认是否为有效负样本。",
                "Task contains no bounding boxes; confirm that it is a valid negative sample.",
            )
        )

    for result_id, choices in choices_by_id.items():
        if result_id not in boxes:
            issues.append(
                _issue(
                    task_id,
                    "MV_ORPHAN_ATTRIBUTE",
                    "error",
                    "moving 属性没有对应 bbox。",
                    "Moving attribute has no matching bounding box.",
                    result={"id": result_id},
                )
            )
            continue
        if len(choices) != len(set(choices)):
            issues.append(
                _issue(
                    task_id,
                    "MV_DUPLICATE_ATTRIBUTE",
                    "warning",
                    "同一 bbox 重复添加了 moving 属性。",
                    "Moving attribute is duplicated on the same bounding box.",
                    result={"id": result_id},
                )
            )
        if "moving" in choices:
            metrics["moving_bboxes"] += 1
            if labels_by_id.get(result_id) != "item":
                issues.append(
                    _issue(
                        task_id,
                        "MV_MOVING_NON_ITEM",
                        "error",
                        "moving 只能关联 item bbox。",
                        "Moving may only be attached to an item bounding box.",
                        result={"id": result_id},
                    )
                )

    for choice_result in choice_results:
        result_id = str(choice_result.get("id", ""))
        box = boxes.get(result_id)
        if box is None:
            continue
        attribute_control = str(choice_result.get("from_name", "")).lower()
        camera_target = str(box.get("to_name", "")).lower()
        if (
            camera_target.endswith(("a", "b"))
            and attribute_control.endswith(("a", "b"))
            and camera_target[-1] != attribute_control[-1]
        ):
            issues.append(
                _issue(
                    task_id,
                    "MV_ATTRIBUTE_CAMERA_MISMATCH",
                    "error",
                    "moving 属性使用了错误相机的控件。",
                    "Moving attribute uses the control for the wrong camera.",
                    choice_result,
                    bbox_camera=camera_target,
                    attribute_control=attribute_control,
                )
            )

    for from_id, to_id in relations:
        if from_id not in boxes or to_id not in boxes:
            issues.append(
                _issue(
                    task_id,
                    "MV_BROKEN_RELATION",
                    "error",
                    "跨视角关系引用了不存在的 bbox。",
                    "Cross-view relation references a missing bounding box.",
                    from_id=from_id,
                    to_id=to_id,
                )
            )
        elif boxes[from_id].get("to_name") == boxes[to_id].get("to_name"):
            issues.append(
                _issue(
                    task_id,
                    "MV_SAME_VIEW_RELATION",
                    "warning",
                    "关系两端来自同一相机，建议复核。",
                    "Both ends of the relation are in the same camera; review manually.",
                    from_id=from_id,
                    to_id=to_id,
                )
            )

    metrics["tasks_with_moving"] += int(metrics["moving_bboxes"] > 0)
    metrics["relations"] += len(relations)
    return issues, metrics
