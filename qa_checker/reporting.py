from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from typing import Any

from qa_checker.models import CheckResult


def issues_csv_bytes(result: CheckResult) -> bytes:
    output = io.StringIO()
    fieldnames = [
        "task_id",
        "result_id",
        "severity",
        "code",
        "message_zh",
        "message_en",
        "details",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for issue in result.issues:
        writer.writerow(issue.to_dict())
    return output.getvalue().encode("utf-8-sig")


def report_payload(result: CheckResult) -> dict[str, Any]:
    sample_by_code: defaultdict[str, list[str]] = defaultdict(list)
    for issue in result.issues:
        if len(sample_by_code[issue.code]) < 20:
            sample_by_code[issue.code].append(issue.task_id)

    return {
        "summary": result.summary(),
        "reviewer_actions": dict(result.reviewer_action_counts),
        "issue_counts": dict(result.issue_counts.most_common()),
        "metrics": dict(result.metric_counts),
        "review_samples": dict(sample_by_code),
        "notes": {
            "zh": (
                "Reviewer 未打回率统计 accepted 和 fixed_and_accepted；"
                "Reviewer 检查覆盖率为已检查任务数除以工具检查任务数；"
                "自动规则通过率只反映 error；warning 需人工复核；"
                "ignore 可忽略且不计入通过率。轮廓贴合、动作语义、"
                "手/背景误入等仍需人工复核。报告不包含标注员邮箱。"
            ),
            "en": (
                "The reviewer no-return rate includes accepted and "
                "fixed_and_accepted tasks. Reviewer coverage is the reviewed "
                "task count divided by the tool-checked task count. "
                "The automated pass rate counts "
                "only error issues. "
                "warning requires human review; ignore can be skipped and "
                "does not affect the pass rate. Geometry fit, action semantics, "
                "and hand/background inclusion still require human review. "
                "Annotator emails are excluded."
            ),
        },
    }


def report_json_bytes(result: CheckResult) -> bytes:
    return json.dumps(
        report_payload(result),
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
