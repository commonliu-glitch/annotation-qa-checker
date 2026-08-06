from __future__ import annotations

import gzip
import io
import json

from qa_checker.engine import run_check
from qa_checker.parsers import resolve_local_path, uploaded_task_stream


def _stream(tasks: list[dict]) -> io.BytesIO:
    return io.BytesIO(json.dumps(tasks).encode())


def _annotation(results: list[dict]) -> list[dict]:
    return [{"id": 1, "updated_at": "2026-01-01", "result": results}]


def test_valid_omnitrack_task_passes_hard_rules() -> None:
    task = {
        "id": 101,
        "data": {"video_url0": "gs://bucket/cam0.mp4", "video_url1": "gs://bucket/cam1.mp4"},
        "annotations": _annotation(
            [
                {
                    "id": "item-1",
                    "type": "videorectangle",
                    "from_name": "rect0",
                    "value": {
                        "labels": ["ITEM1"],
                        "sequence": [
                            {"frame": 1, "x": 10, "y": 10, "width": 20, "height": 20},
                            {"frame": 3, "x": 12, "y": 12, "width": 20, "height": 20},
                        ],
                    },
                },
                {
                    "id": "item-1",
                    "type": "choices",
                    "from_name": "whole_clip0",
                    "value": {"choices": ["Add"]},
                },
                {
                    "id": "item-1",
                    "type": "choices",
                    "from_name": "product_type0",
                    "value": {"choices": ["Barcoded Item"]},
                },
                {
                    "id": "barcode-1",
                    "type": "videorectangle",
                    "value": {
                        "labels": ["Barcode"],
                        "sequence": [
                            {"frame": 1, "x": 12, "y": 12, "width": 3, "height": 2}
                        ],
                    },
                },
                {
                    "type": "relation",
                    "from_id": "barcode-1",
                    "to_id": "item-1",
                },
            ]
        ),
    }

    result = run_check(_stream([task]), "omni.json")

    assert result.project_type == "omnitrack"
    assert result.tasks_checked == 1
    assert not result.tasks_with_errors


def test_omnitrack_detects_missing_action_and_bad_geometry() -> None:
    task = {
        "id": 102,
        "data": {"video_url0": "a", "video_url1": "b"},
        "annotations": _annotation(
            [
                {
                    "id": "item-1",
                    "type": "videorectangle",
                    "value": {
                        "labels": ["ITEM1"],
                        "sequence": [
                            {"frame": 1, "x": 90, "y": 10, "width": 20, "height": 20}
                        ],
                    },
                }
            ]
        ),
    }

    result = run_check(_stream([task]), "omni.json")

    assert result.issue_counts["OT_ACTION_COUNT"] == 1
    assert result.issue_counts["OT_OUT_OF_BOUNDS"] == 1


def test_valid_multiview_task_and_moving_metric() -> None:
    task = {
        "id": 201,
        "data": {"imageA": "gs://bucket/a.jpg", "imageB": "gs://bucket/b.jpg"},
        "annotations": _annotation(
            [
                {
                    "id": "bbox-a",
                    "type": "rectanglelabels",
                    "to_name": "imgA",
                    "value": {
                        "x": 10,
                        "y": 10,
                        "width": 20,
                        "height": 20,
                        "rectanglelabels": ["item"],
                    },
                },
                {
                    "id": "bbox-a",
                    "type": "choices",
                    "from_name": "bbox_tag_A",
                    "value": {"choices": ["moving"]},
                },
            ]
        ),
    }

    result = run_check(_stream([task]), "mv.json")

    assert result.project_type == "multiview"
    assert not result.tasks_with_errors
    assert result.metric_counts["moving_bboxes"] == 1


def test_multiview_detects_orphan_attribute() -> None:
    task = {
        "id": 202,
        "data": {"imageA": "a", "imageB": "b"},
        "annotations": _annotation(
            [
                {
                    "id": "missing-box",
                    "type": "choices",
                    "value": {"choices": ["moving"]},
                }
            ]
        ),
    }

    result = run_check(_stream([task]), "mv.json")

    assert result.issue_counts["MV_ORPHAN_ATTRIBUTE"] == 1
    assert result.issue_counts["MV_NO_BBOX"] == 1


def test_realistic_omnitrack_vector_item_is_supported() -> None:
    task = {
        "id": 103,
        "data": {"video_url0": "a", "video_url1": "b"},
        "annotations": _annotation(
            [
                {
                    "id": "item-mask",
                    "type": "videovectorlabels",
                    "value": {
                        "videovectorlabels": ["ITEM1"],
                        "sequence": [
                            {
                                "frame": 1,
                                "vertices": [
                                    {"x": 10, "y": 10},
                                    {"x": 20, "y": 10},
                                    {"x": 20, "y": 20},
                                ],
                            }
                        ],
                    },
                },
                {
                    "id": "item-mask",
                    "type": "choices",
                    "from_name": "whole_clip0",
                    "value": {"choices": ["stationary"]},
                },
                {
                    "id": "item-mask",
                    "type": "choices",
                    "from_name": "product_type0",
                    "value": {"choices": ["reusable bag"]},
                },
            ]
        ),
    }

    result = run_check(_stream([task]), "omni.json")

    assert result.metric_counts["item_tracks"] == 1
    assert not result.tasks_with_errors


def test_multiview_detects_attribute_camera_mismatch() -> None:
    task = {
        "id": 203,
        "data": {"imageA": "a", "imageB": "b"},
        "annotations": _annotation(
            [
                {
                    "id": "bbox-b",
                    "type": "rectanglelabels",
                    "to_name": "imgB",
                    "value": {
                        "x": 10,
                        "y": 10,
                        "width": 20,
                        "height": 20,
                        "rectanglelabels": ["item"],
                    },
                },
                {
                    "id": "bbox-b",
                    "type": "choices",
                    "from_name": "bbox_tag_A",
                    "value": {"choices": ["moving"]},
                },
            ]
        ),
    }

    result = run_check(_stream([task]), "mv.json")

    assert result.issue_counts["MV_ATTRIBUTE_CAMERA_MISMATCH"] == 1


def test_path_resolver_handles_trailing_space_directory(tmp_path) -> None:
    spaced_dir = tmp_path / "export "
    spaced_dir.mkdir()
    export_file = spaced_dir / "tasks.json"
    export_file.write_text("[]")

    typed_without_space = str(tmp_path / "export" / "tasks.json")

    assert resolve_local_path(typed_without_space) == export_file


def test_uploaded_gzip_stream_is_checked() -> None:
    task = {
        "id": 204,
        "data": {"imageA": "a", "imageB": "b"},
        "annotations": _annotation([]),
    }
    compressed = io.BytesIO(gzip.compress(json.dumps([task]).encode()))

    stream = uploaded_task_stream(compressed, "tasks.json.gz")
    result = run_check(stream, "tasks.json.gz")
    stream.close()

    assert result.project_type == "multiview"
    assert result.tasks_checked == 1
