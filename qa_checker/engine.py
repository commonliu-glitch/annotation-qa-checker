from __future__ import annotations

from itertools import chain
from typing import BinaryIO, Callable, Literal

from qa_checker.models import CheckResult, ProjectType
from qa_checker.parsers import detect_project_type, iter_tasks
from qa_checker.rules import multiview, omnitrack

ProgressCallback = Callable[[int], None]


def run_check(
    stream: BinaryIO,
    source_name: str,
    project_type: ProjectType | Literal["auto"] = "auto",
    task_limit: int = 0,
    max_issues: int = 50_000,
    progress_callback: ProgressCallback | None = None,
) -> CheckResult:
    tasks = iter_tasks(stream)
    try:
        first_task = next(tasks)
    except StopIteration as error:
        raise ValueError("JSON 顶层数组为空，没有可检查的任务。") from error

    detected_type = detect_project_type(first_task)
    selected_type = detected_type if project_type == "auto" else project_type
    if project_type != "auto" and project_type != detected_type:
        raise ValueError(
            f"选择的项目类型是 {project_type}，但文件结构更像 {detected_type}。"
        )

    result = CheckResult(
        project_type=selected_type,
        source_name=source_name,
        max_issues=max_issues,
    )
    checker = omnitrack.check_task if selected_type == "omnitrack" else multiview.check_task

    for task in chain([first_task], tasks):
        if task_limit and result.tasks_checked >= task_limit:
            break
        result.tasks_checked += 1
        issues, metrics = checker(task)
        for issue in issues:
            result.add_issue(issue)
        result.metric_counts.update(metrics)
        if progress_callback and result.tasks_checked % 250 == 0:
            progress_callback(result.tasks_checked)

    if progress_callback:
        progress_callback(result.tasks_checked)
    return result
