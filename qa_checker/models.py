from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Severity = Literal["error", "warning", "ignore", "info"]
ProjectType = Literal["omnitrack", "multiview"]


@dataclass
class Issue:
    task_id: str
    code: str
    severity: Severity
    message_zh: str
    message_en: str
    result_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["details"] = "; ".join(
            f"{key}={value}" for key, value in self.details.items()
        )
        return row


@dataclass
class CheckResult:
    project_type: ProjectType
    source_name: str
    tasks_checked: int = 0
    tasks_with_errors: set[str] = field(default_factory=set)
    tasks_with_warnings: set[str] = field(default_factory=set)
    tasks_with_ignores: set[str] = field(default_factory=set)
    issue_counts: Counter[str] = field(default_factory=Counter)
    severity_counts: Counter[str] = field(default_factory=Counter)
    metric_counts: Counter[str] = field(default_factory=Counter)
    reviewer_action_counts: Counter[str] = field(default_factory=Counter)
    issues: list[Issue] = field(default_factory=list)
    issues_truncated: bool = False
    max_issues: int = 50_000

    def add_issue(self, issue: Issue) -> None:
        self.issue_counts[issue.code] += 1
        self.severity_counts[issue.severity] += 1
        if issue.severity == "error":
            self.tasks_with_errors.add(issue.task_id)
        elif issue.severity == "warning":
            self.tasks_with_warnings.add(issue.task_id)
        elif issue.severity == "ignore":
            self.tasks_with_ignores.add(issue.task_id)

        if len(self.issues) < self.max_issues:
            self.issues.append(issue)
        else:
            self.issues_truncated = True

    @property
    def hard_pass_rate(self) -> float:
        if not self.tasks_checked:
            return 0.0
        return (self.tasks_checked - len(self.tasks_with_errors)) / self.tasks_checked

    @property
    def reviewer_checked_count(self) -> int:
        return sum(
            self.reviewer_action_counts[action]
            for action in ("accepted", "fixed_and_accepted", "rejected")
        )

    @property
    def reviewer_not_returned_count(self) -> int:
        return (
            self.reviewer_action_counts["accepted"]
            + self.reviewer_action_counts["fixed_and_accepted"]
        )

    @property
    def reviewer_not_returned_rate(self) -> float | None:
        if not self.reviewer_checked_count:
            return None
        return self.reviewer_not_returned_count / self.reviewer_checked_count

    @property
    def reviewer_coverage_rate(self) -> float:
        if not self.tasks_checked:
            return 0.0
        return self.reviewer_checked_count / self.tasks_checked

    def summary(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "project_type": self.project_type,
            "tasks_checked": self.tasks_checked,
            "tasks_with_errors": len(self.tasks_with_errors),
            "tasks_with_warnings": len(self.tasks_with_warnings),
            "tasks_with_ignores": len(self.tasks_with_ignores),
            "hard_pass_rate": round(self.hard_pass_rate, 4),
            "reviewer_checked_count": self.reviewer_checked_count,
            "reviewer_coverage_rate": round(self.reviewer_coverage_rate, 4),
            "reviewer_not_returned_count": self.reviewer_not_returned_count,
            "reviewer_not_returned_rate": (
                round(self.reviewer_not_returned_rate, 4)
                if self.reviewer_not_returned_rate is not None
                else None
            ),
            "reviewer_accepted_count": self.reviewer_action_counts["accepted"],
            "reviewer_fixed_and_accepted_count": self.reviewer_action_counts[
                "fixed_and_accepted"
            ],
            "reviewer_rejected_count": self.reviewer_action_counts["rejected"],
            "error_count": self.severity_counts["error"],
            "warning_count": self.severity_counts["warning"],
            "ignore_count": self.severity_counts["ignore"],
            "info_count": self.severity_counts["info"],
            "issues_truncated": self.issues_truncated,
        }
