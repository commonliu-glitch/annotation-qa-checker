from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

from qa_checker.models import Issue
from qa_checker.parsers import annotation_results, latest_annotation

ITEM_PATTERN = re.compile(r"^ITEM[1-7]$", re.IGNORECASE)
ALLOWED_ACTIONS = {
    "stationary",
    "add",
    "remove",
    "shuffling",
    "struggling",
    "scanning",
    "unknown",
    "nothing",
    "unknown / nothing",
}
ALLOWED_PRODUCT_TYPES = {
    "barcoded item",
    "produce",
    "produce in bag",
    "personal",
    "personal item",
    "reusable",
    "reusable bag",
    "unknown",
    "not sure",
}


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


def _geometry_issues(
    task_id: str, result: dict[str, Any], sequence: list[dict[str, Any]]
) -> list[Issue]:
    issues: list[Issue] = []
    seen_frames: set[int] = set()
    previous: tuple[int, float, float, float] | None = None

    for point in sequence:
        frame = point.get("frame")
        if not isinstance(frame, int) or frame < 0:
            issues.append(
                _issue(
                    task_id,
                    "OT_INVALID_FRAME",
                    "error",
                    "轨迹包含无效帧号。",
                    "Track contains an invalid frame number.",
                    result,
                    frame=frame,
                )
            )
            continue
        if frame in seen_frames:
            issues.append(
                _issue(
                    task_id,
                    "OT_DUPLICATE_FRAME",
                    "error",
                    "同一轨迹内存在重复帧。",
                    "Duplicate frame found within the same track.",
                    result,
                    frame=frame,
                )
            )
        seen_frames.add(frame)

        try:
            x = float(point["x"])
            y = float(point["y"])
            width = float(point["width"])
            height = float(point["height"])
        except (KeyError, TypeError, ValueError):
            issues.append(
                _issue(
                    task_id,
                    "OT_INVALID_GEOMETRY",
                    "error",
                    "轨迹点缺少有效坐标。",
                    "Track point is missing valid geometry.",
                    result,
                    frame=frame,
                )
            )
            continue

        if (
            width <= 0
            or height <= 0
            or x < 0
            or y < 0
            or x + width > 100.5
            or y + height > 100.5
        ):
            issues.append(
                _issue(
                    task_id,
                    "OT_OUT_OF_BOUNDS",
                    "error",
                    "框坐标为空或超出画面范围。",
                    "Box is empty or outside the image bounds.",
                    result,
                    frame=frame,
                )
            )

        center_x, center_y = x + width / 2, y + height / 2
        area = width * height
        if previous is not None:
            prev_frame, prev_x, prev_y, prev_area = previous
            if frame <= prev_frame:
                issues.append(
                    _issue(
                        task_id,
                        "OT_FRAME_ORDER",
                        "error",
                        "轨迹关键帧未按时间递增。",
                        "Track keyframes are not in ascending order.",
                        result,
                        frame=frame,
                        previous_frame=prev_frame,
                    )
                )
            distance = math.hypot(center_x - prev_x, center_y - prev_y)
            if 0 < frame - prev_frame <= 5 and distance > 35:
                issues.append(
                    _issue(
                        task_id,
                        "OT_SUDDEN_JUMP",
                        "warning",
                        "相邻关键帧位置突跳，建议人工复核。",
                        "Sudden movement between nearby keyframes; review manually.",
                        result,
                        frame=frame,
                        distance_percent=round(distance, 1),
                    )
                )
            if prev_area > 0 and (area / prev_area > 4 or area / prev_area < 0.25):
                issues.append(
                    _issue(
                        task_id,
                        "OT_AREA_JUMP",
                        "warning",
                        "相邻关键帧面积变化异常，建议人工复核。",
                        "Large area change between keyframes; review manually.",
                        result,
                        frame=frame,
                    )
                )
        previous = (frame, center_x, center_y, area)
    return issues


def _vector_geometry_issues(
    task_id: str, result: dict[str, Any], sequence: list[dict[str, Any]]
) -> list[Issue]:
    issues: list[Issue] = []
    seen_frames: set[int] = set()
    previous_frame = -1
    for point in sequence:
        frame = point.get("frame")
        if not isinstance(frame, int) or frame < 0:
            issues.append(
                _issue(
                    task_id,
                    "OT_INVALID_FRAME",
                    "error",
                    "掩码轨迹包含无效帧号。",
                    "Mask track contains an invalid frame number.",
                    result,
                    frame=frame,
                )
            )
            continue
        if frame in seen_frames:
            issues.append(
                _issue(
                    task_id,
                    "OT_DUPLICATE_FRAME",
                    "error",
                    "同一掩码轨迹内存在重复帧。",
                    "Duplicate frame found within the same mask track.",
                    result,
                    frame=frame,
                )
            )
        if frame <= previous_frame:
            issues.append(
                _issue(
                    task_id,
                    "OT_FRAME_ORDER",
                    "error",
                    "掩码关键帧未按时间递增。",
                    "Mask keyframes are not in ascending order.",
                    result,
                    frame=frame,
                    previous_frame=previous_frame,
                )
            )
        seen_frames.add(frame)
        previous_frame = frame

        vertices = point.get("vertices", [])
        if not isinstance(vertices, list) or len(vertices) < 3:
            issues.append(
                _issue(
                    task_id,
                    "OT_INVALID_POLYGON",
                    "error",
                    "掩码多边形少于 3 个有效点。",
                    "Mask polygon has fewer than three valid vertices.",
                    result,
                    frame=frame,
                )
            )
            continue
        for vertex in vertices:
            try:
                x = float(vertex["x"])
                y = float(vertex["y"])
            except (KeyError, TypeError, ValueError):
                issues.append(
                    _issue(
                        task_id,
                        "OT_INVALID_POLYGON",
                        "error",
                        "掩码多边形包含无效坐标。",
                        "Mask polygon contains invalid coordinates.",
                        result,
                        frame=frame,
                    )
                )
                break
            if not (0 <= x <= 100.5 and 0 <= y <= 100.5):
                issues.append(
                    _issue(
                        task_id,
                        "OT_POLYGON_OUT_OF_BOUNDS",
                        "error",
                        "掩码多边形坐标超出画面范围。",
                        "Mask polygon coordinate is outside image bounds.",
                        result,
                        frame=frame,
                    )
                )
                break
    return issues


def _camera_hint(result: dict[str, Any]) -> str:
    to_name = str(result.get("to_name", "")).lower()
    from_name = str(result.get("from_name", "")).lower()
    for candidate in (to_name, from_name):
        if candidate.endswith("0") or "cam0" in candidate:
            return "cam0"
        if candidate.endswith("1") or "cam1" in candidate:
            return "cam1"
    return "unknown"


def _barcode_keyframe_gap_issues(
    task_id: str, result: dict[str, Any], sequence: list[dict[str, Any]]
) -> list[Issue]:
    frames = sorted(
        {
            point.get("frame")
            for point in sequence
            if isinstance(point.get("frame"), int) and point.get("frame") >= 0
        }
    )
    issues: list[Issue] = []
    for previous, current in zip(frames, frames[1:]):
        gap = current - previous
        if gap > 3:
            issues.append(
                _issue(
                    task_id,
                    "OT_BARCODE_KEYFRAME_GAP",
                    "ignore",
                    "Barcode 关键帧间隔超过 3 帧，可忽略。",
                    "Barcode keyframe gap exceeds 3 frames; this can be ignored.",
                    result,
                    previous_frame=previous,
                    frame=current,
                    gap=gap,
                )
            )
    return issues


def check_task(task: dict[str, Any]) -> tuple[list[Issue], Counter[str]]:
    task_id = str(task.get("id", "unknown"))
    issues: list[Issue] = []
    metrics: Counter[str] = Counter()

    if latest_annotation(task) is None:
        return [
            _issue(
                task_id,
                "OT_NO_ANNOTATION",
                "error",
                "任务没有有效标注。",
                "Task has no valid annotation.",
            )
        ], metrics

    data = task.get("data", {})
    video_keys = [key for key, value in data.items() if key.startswith("video_url") and value]
    if len(video_keys) < 2:
        issues.append(
            _issue(
                task_id,
                "OT_MISSING_VIDEO_VIEW",
                "error",
                "任务缺少双相机视频字段。",
                "Task does not contain both camera video fields.",
                views=len(video_keys),
            )
        )

    results = annotation_results(task)
    rectangles: dict[str, str] = {}
    item_result_ids: set[str] = set()
    barcode_result_ids: set[str] = set()
    actions_by_item: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    products_by_item: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    relations: list[tuple[str, str]] = []

    for result in results:
        result_type = str(result.get("type", "")).lower()
        result_id = str(result.get("id", ""))
        value = result.get("value", {})

        if result_type in {"videorectangle", "videovectorlabels"}:
            label_field = "labels" if result_type == "videorectangle" else "videovectorlabels"
            labels = value.get(label_field, [])
            label = str(labels[0]) if labels else ""
            rectangles[result_id] = label
            sequence = value.get("sequence", [])
            if not label or not (ITEM_PATTERN.match(label) or label.lower() == "barcode"):
                issues.append(
                    _issue(
                        task_id,
                        "OT_INVALID_LABEL",
                        "error",
                        "发现不在规范中的轨迹标签。",
                        "Track label is not allowed by the guideline.",
                        result,
                        label=label,
                    )
                )
            if ITEM_PATTERN.match(label):
                item_result_ids.add(result_id)
                metrics["item_tracks"] += 1
            elif label.lower() == "barcode":
                barcode_result_ids.add(result_id)
                metrics["barcode_tracks"] += 1
            if not sequence:
                issues.append(
                    _issue(
                        task_id,
                        "OT_EMPTY_TRACK",
                        "error",
                        "轨迹没有任何关键帧。",
                        "Track has no keyframes.",
                        result,
                    )
                )
            else:
                if result_type == "videorectangle":
                    issues.extend(_geometry_issues(task_id, result, sequence))
                else:
                    issues.extend(_vector_geometry_issues(task_id, result, sequence))
                if label.lower() == "barcode":
                    issues.extend(_barcode_keyframe_gap_issues(task_id, result, sequence))

        elif result_type == "relation":
            relations.append((str(result.get("from_id", "")), str(result.get("to_id", ""))))

    for result in results:
        result_id = str(result.get("id", ""))
        from_name = str(result.get("from_name", "")).lower()
        choices = [str(value) for value in result.get("value", {}).get("choices", [])]
        item_label = rectangles.get(result_id, result_id)
        camera = _camera_hint(result)

        if "whole_clip" in from_name or "action" in from_name:
            for choice in choices:
                actions_by_item[item_label].append((choice, camera))
                if choice.strip().lower() not in ALLOWED_ACTIONS:
                    issues.append(
                        _issue(
                            task_id,
                            "OT_INVALID_ACTION",
                            "error",
                            "发现不在规范中的 action。",
                            "Action is not allowed by the guideline.",
                            result,
                            action=choice,
                        )
                    )
        elif "product_type" in from_name:
            for choice in choices:
                products_by_item[item_label].append((choice, camera))
                if choice.strip().lower() not in ALLOWED_PRODUCT_TYPES:
                    issues.append(
                        _issue(
                            task_id,
                            "OT_INVALID_PRODUCT_TYPE",
                            "error",
                            "发现不在规范中的商品类型。",
                            "Product type is not allowed by the guideline.",
                            result,
                            product_type=choice,
                        )
                    )

    item_labels = {rectangles[result_id] for result_id in item_result_ids}
    for item_label in item_labels:
        actions = actions_by_item.get(item_label, [])
        action_cameras = {camera for _, camera in actions}
        if not actions:
            issues.append(
                _issue(
                    task_id,
                    "OT_ACTION_COUNT",
                    "error",
                    "每个 ITEM 必须且只能有一个 whole-clip action。",
                    "Each ITEM must have exactly one whole-clip action.",
                    item=item_label,
                    action_count=0,
                )
            )
        elif len(action_cameras) > 1:
            issues.append(
                _issue(
                    task_id,
                    "OT_ACTION_BOTH_CAMERAS",
                    "error",
                    "同一 ITEM 在 cam0 和 cam1 都标了 Action；优先只在 cam0 标注。",
                    "The same ITEM has Action on both cameras; annotate only on cam0 when possible.",
                    item=item_label,
                    cameras="|".join(sorted(action_cameras)),
                    action_count=len(actions),
                )
            )
        elif len(actions) != 1:
            issues.append(
                _issue(
                    task_id,
                    "OT_ACTION_COUNT",
                    "error",
                    "每个 ITEM 必须且只能有一个 whole-clip action。",
                    "Each ITEM must have exactly one whole-clip action.",
                    item=item_label,
                    action_count=len(actions),
                )
            )

        products = products_by_item.get(item_label, [])
        product_values = [value for value, _ in products]
        product_cameras = {camera for _, camera in products}
        if not products:
            issues.append(
                _issue(
                    task_id,
                    "OT_MISSING_PRODUCT_TYPE",
                    "warning",
                    "ITEM 缺少商品类型，建议补充。",
                    "ITEM is missing a product type; please add one.",
                    item=item_label,
                )
            )
        elif len(set(product_values)) > 1:
            issues.append(
                _issue(
                    task_id,
                    "OT_PRODUCT_CONFLICT",
                    "error",
                    "同一 ITEM 存在冲突的商品类型。",
                    "The same ITEM has conflicting product types.",
                    item=item_label,
                    product_types="|".join(product_values),
                )
            )
        elif len(product_cameras) > 1:
            issues.append(
                _issue(
                    task_id,
                    "OT_PRODUCT_BOTH_CAMERAS",
                    "error",
                    "同一 ITEM 在 cam0 和 cam1 都标了商品类型；优先只在 cam0 标注。",
                    "The same ITEM has product type on both cameras; annotate only on cam0 when possible.",
                    item=item_label,
                    cameras="|".join(sorted(product_cameras)),
                )
            )

    linked_barcodes: set[str] = set()
    for from_id, to_id in relations:
        if from_id in barcode_result_ids and to_id in item_result_ids:
            linked_barcodes.add(from_id)
        elif to_id in barcode_result_ids and from_id in item_result_ids:
            linked_barcodes.add(to_id)
        else:
            issues.append(
                _issue(
                    task_id,
                    "OT_INVALID_RELATION",
                    "error",
                    "关系未正确连接 Barcode 与 ITEM。",
                    "Relation does not correctly connect a Barcode and an ITEM.",
                    from_id=from_id,
                    to_id=to_id,
                )
            )
    for barcode_id in barcode_result_ids - linked_barcodes:
        issues.append(
            _issue(
                task_id,
                "OT_ORPHAN_BARCODE",
                "error",
                "Barcode 未关联到 ITEM。",
                "Barcode is not linked to an ITEM.",
                result={"id": barcode_id},
            )
        )

    metrics["tasks_with_items"] += int(bool(item_result_ids))
    metrics["tasks_with_barcodes"] += int(bool(barcode_result_ids))
    return issues, metrics
