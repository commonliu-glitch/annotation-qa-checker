from __future__ import annotations

import gzip
import io
import json

from qa_checker.engine import run_check
from qa_checker.parsers import resolve_local_path, uploaded_task_stream
from qa_checker.reporting import report_payload


def _stream(tasks: list[dict]) -> io.BytesIO:
    return io.BytesIO(json.dumps(tasks).encode())


def _annotation(results: list[dict]) -> list[dict]:
    return [{"id": 1, "updated_at": "2026-01-01", "result": results}]


def _multiview_task(task_id: int, last_action: str | None = None) -> dict:
    annotation = {
        "id": task_id,
        "updated_at": "2026-01-01",
        "result": [
            {
                "id": f"bbox-{task_id}",
                "type": "rectanglelabels",
                "to_name": "imgA",
                "value": {
                    "x": 10,
                    "y": 10,
                    "width": 20,
                    "height": 20,
                    "rectanglelabels": ["item"],
                },
            }
        ],
    }
    if last_action is not None:
        annotation["last_action"] = last_action
    return {
        "id": task_id,
        "data": {"imageA": "a", "imageB": "b"},
        "annotations": [annotation],
    }


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


def test_orphan_barcode_is_error() -> None:
    task = {
        "id": 105,
        "data": {"video_url0": "a", "video_url1": "b"},
        "annotations": _annotation(
            [
                {
                    "id": "item-1",
                    "type": "videovectorlabels",
                    "to_name": "cam0",
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
                    "id": "item-1",
                    "type": "choices",
                    "from_name": "whole_clip0",
                    "to_name": "cam0",
                    "value": {"choices": ["add"]},
                },
                {
                    "id": "item-1",
                    "type": "choices",
                    "from_name": "product_type0",
                    "to_name": "cam0",
                    "value": {"choices": ["barcoded item"]},
                },
                {
                    "id": "barcode-1",
                    "type": "videorectangle",
                    "to_name": "cam0",
                    "value": {
                        "labels": ["Barcode"],
                        "sequence": [
                            {"frame": 1, "x": 12, "y": 12, "width": 3, "height": 2}
                        ],
                    },
                },
            ]
        ),
    }

    result = run_check(_stream([task]), "omni.json")

    assert result.issue_counts["OT_ORPHAN_BARCODE"] == 1
    assert "105" in result.tasks_with_errors


def test_barcode_keyframe_gap_is_ignore() -> None:
    task = {
        "id": 106,
        "data": {"video_url0": "a", "video_url1": "b"},
        "annotations": _annotation(
            [
                {
                    "id": "item-1",
                    "type": "videovectorlabels",
                    "to_name": "cam0",
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
                    "id": "item-1",
                    "type": "choices",
                    "from_name": "whole_clip0",
                    "to_name": "cam0",
                    "value": {"choices": ["add"]},
                },
                {
                    "id": "item-1",
                    "type": "choices",
                    "from_name": "product_type0",
                    "to_name": "cam0",
                    "value": {"choices": ["barcoded item"]},
                },
                {
                    "id": "barcode-1",
                    "type": "videorectangle",
                    "to_name": "cam0",
                    "value": {
                        "labels": ["Barcode"],
                        "sequence": [
                            {"frame": 1, "x": 12, "y": 12, "width": 3, "height": 2},
                            {"frame": 8, "x": 13, "y": 13, "width": 3, "height": 2},
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

    assert result.issue_counts["OT_BARCODE_KEYFRAME_GAP"] == 1
    assert result.severity_counts["ignore"] == 1
    assert not result.tasks_with_errors
    assert result.hard_pass_rate == 1.0


def test_action_on_both_cameras_and_missing_product_type() -> None:
    task = {
        "id": 107,
        "data": {"video_url0": "a", "video_url1": "b"},
        "annotations": _annotation(
            [
                {
                    "id": "item-cam0",
                    "type": "videovectorlabels",
                    "to_name": "cam0",
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
                    "id": "item-cam1",
                    "type": "videovectorlabels",
                    "to_name": "cam1",
                    "value": {
                        "videovectorlabels": ["ITEM1"],
                        "sequence": [
                            {
                                "frame": 1,
                                "vertices": [
                                    {"x": 11, "y": 11},
                                    {"x": 21, "y": 11},
                                    {"x": 21, "y": 21},
                                ],
                            }
                        ],
                    },
                },
                {
                    "id": "item-cam0",
                    "type": "choices",
                    "from_name": "whole_clip0",
                    "to_name": "cam0",
                    "value": {"choices": ["add"]},
                },
                {
                    "id": "item-cam1",
                    "type": "choices",
                    "from_name": "whole_clip1",
                    "to_name": "cam1",
                    "value": {"choices": ["add"]},
                },
            ]
        ),
    }

    result = run_check(_stream([task]), "omni.json")

    assert result.issue_counts["OT_ACTION_BOTH_CAMERAS"] == 1
    assert result.issue_counts["OT_MISSING_PRODUCT_TYPE"] == 1
    assert "107" in result.tasks_with_errors
    assert "107" in result.tasks_with_warnings


def test_reviewer_not_returned_rate_uses_final_review_actions() -> None:
    tasks = [
        _multiview_task(301, "accepted"),
        _multiview_task(302, "fixed_and_accepted"),
        _multiview_task(303, "rejected"),
        _multiview_task(304, "skipped"),
        _multiview_task(305),
    ]

    result = run_check(_stream(tasks), "reviewed.json")
    summary = result.summary()

    assert result.reviewer_action_counts == {
        "accepted": 1,
        "fixed_and_accepted": 1,
        "rejected": 1,
    }
    assert summary["reviewer_checked_count"] == 3
    assert summary["reviewer_coverage_rate"] == 0.6
    assert summary["reviewer_not_returned_count"] == 2
    assert summary["reviewer_not_returned_rate"] == 0.6667
    assert summary["reviewer_fixed_and_accepted_count"] == 1
    assert result.hard_pass_rate == 1.0
    assert report_payload(result)["reviewer_actions"]["rejected"] == 1


def test_reviewer_rate_is_none_when_no_tasks_were_reviewed() -> None:
    result = run_check(_stream([_multiview_task(306, "skipped")]), "unreviewed.json")

    assert result.reviewer_checked_count == 0
    assert result.reviewer_coverage_rate == 0.0
    assert result.reviewer_not_returned_rate is None
    assert result.summary()["reviewer_not_returned_rate"] is None
