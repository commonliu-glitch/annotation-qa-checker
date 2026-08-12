from __future__ import annotations

from pathlib import Path

import streamlit as st

from qa_checker.auth import is_local_mode, require_authentication
from qa_checker.engine import run_check
from qa_checker.parsers import (
    is_supported_filename,
    open_task_stream,
    resolve_local_path,
    uploaded_task_stream,
)
from qa_checker.reporting import issues_csv_bytes, report_json_bytes


def _format_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def _progress_ratio(checked: int, expected_total):

    if expected_total and expected_total > 0:
        return min(checked / expected_total, 0.99)
    # Unknown total: approach 99% slowly so the bar keeps moving.
    return min(0.99, 1 - (0.985 ** max(checked, 1)))


def _format_percentage(value: float) -> str:
    return f"{value:.2%}" if 0 < value < 0.01 else f"{value:.1%}"


st.set_page_config(page_title="Annotation QA Checker", page_icon="✓", layout="wide")
require_authentication()

st.title("标注质量门禁 / Annotation QA Checker")
st.caption(
    "在上传或交付前检查 OmniTrack 与 Multiview Label Studio JSON。"
    "文件仅用于本次检查，不写入持久化存储。"
)

local_mode = is_local_mode()
with st.sidebar:
    st.header("检查设置 / Settings")
    if local_mode:
        source_mode = st.radio(
            "数据来源 / Source",
            ["本地文件路径（大文件推荐）", "上传文件 / Upload"],
        )
    else:
        source_mode = "上传文件 / Upload"
    project_label = st.selectbox(
        "项目类型 / Project type",
        ["自动识别 / Auto", "OmniTrack", "Multiview"],
    )
    project_type = {
        "自动识别 / Auto": "auto",
        "OmniTrack": "omnitrack",
        "Multiview": "multiview",
    }[project_label]
    task_limit = st.number_input(
        "最多检查任务数（0 为全部）/ Task limit",
        min_value=0,
        value=0,
        step=100,
        help="首次验证超大文件时可先填写 100 或 1000。",
    )
    max_issues = st.number_input(
        "报告最多保留问题数 / Max issue rows",
        min_value=1_000,
        value=50_000,
        step=1_000,
    )

local_path = ""
uploaded_file = None
if local_mode and source_mode.startswith("本地"):
    local_path = st.text_input(
        "JSON 或 JSON.GZ 文件路径 / File path",
        placeholder="/Users/name/Downloads/export.json.gz",
    )
    st.info("本地模式会逐条流式读取 JSON 或 JSON.GZ。")
    if local_path.strip():
        path = resolve_local_path(local_path)
        if path.is_file() and is_supported_filename(path.name):
            st.success(
                f"文件已就绪 / File ready: `{path.name}`（{_format_size(path.stat().st_size)}）"
            )
        elif local_path.strip():
            st.warning("尚未找到有效文件，请检查路径。 / File not found yet.")
else:
    st.warning(
        "大文件上传时请耐心等待，不要刷新页面。"
        " / Please wait while large files upload — do not refresh."
    )
    uploaded_file = st.file_uploader(
        "上传 Label Studio JSON 或 JSON.GZ",
        type=["json", "gz"],
    )
    st.info(
        "建议上传压缩后的 .json.gz，压缩文件上限为 500 MB。"
        "文件不会写入持久化存储。"
    )
    if uploaded_file is not None:
        st.success(
            f"上传完成，文件已就绪 / Upload complete: `{uploaded_file.name}`"
            f"（{_format_size(uploaded_file.size)}）"
        )
        st.progress(1.0, text="上传完成，可以开始检查 / Upload finished — ready to run QA")

if st.button("开始检查 / Run QA", type="primary"):
    status_box = st.status("正在准备检查 / Preparing QA…", expanded=True)
    progress_bar = st.progress(0, text="准备中 / Preparing…")
    detail = st.empty()

    def update_progress(checked: int, expected_total: int | None) -> None:
        ratio = _progress_ratio(checked, expected_total)
        if expected_total:
            label = (
                f"正在检查 {checked:,} / {expected_total:,} 个任务"
                f" / Checking {checked:,} / {expected_total:,} tasks"
            )
        else:
            label = (
                f"正在检查第 {checked:,} 个任务（总量未知，请勿刷新）"
                f" / Checking task {checked:,} (total unknown — do not refresh)"
            )
        progress_bar.progress(ratio, text=label)
        detail.info(label)
        status_box.update(label=label, state="running")

    try:
        if local_mode and source_mode.startswith("本地"):
            path = resolve_local_path(local_path)
            if not path.is_file():
                raise ValueError("找不到该文件，请检查路径和空格。")
            if not is_supported_filename(path.name):
                raise ValueError("请选择 .json 或 .json.gz 文件。")
            progress_bar.progress(0.02, text="正在打开本地文件 / Opening local file…")
            detail.info(f"正在打开：{path.name}")
            with open_task_stream(path) as stream:
                progress_bar.progress(0.05, text="开始解析与检查 / Parsing and checking…")
                checked = run_check(
                    stream,
                    source_name=path.name,
                    project_type=project_type,  # type: ignore[arg-type]
                    task_limit=int(task_limit),
                    max_issues=int(max_issues),
                    progress_callback=update_progress,
                )
        else:
            if uploaded_file is None:
                raise ValueError("请先上传 JSON 或 JSON.GZ 文件。")
            if not is_supported_filename(uploaded_file.name):
                raise ValueError("请选择 .json 或 .json.gz 文件。")
            progress_bar.progress(0.05, text="正在读取上传文件 / Reading uploaded file…")
            detail.info(f"正在读取：{uploaded_file.name}")
            stream = uploaded_task_stream(uploaded_file, uploaded_file.name)
            try:
                progress_bar.progress(0.08, text="开始解析与检查 / Parsing and checking…")
                checked = run_check(
                    stream,
                    source_name=uploaded_file.name,
                    project_type=project_type,  # type: ignore[arg-type]
                    task_limit=int(task_limit),
                    max_issues=int(max_issues),
                    progress_callback=update_progress,
                )
            finally:
                if stream is not uploaded_file:
                    stream.close()

        progress_bar.progress(0.97, text="正在生成报告 / Building report…")
        detail.info("正在整理结果 / Finalizing results…")
        st.session_state["check_result"] = checked
        progress_bar.progress(
            1.0,
            text=f"检查完成：{checked.tasks_checked:,} 个任务 / Done: {checked.tasks_checked:,} tasks",
        )
        status_box.update(
            label=f"检查完成：{checked.tasks_checked:,} 个任务 / QA finished",
            state="complete",
        )
        detail.success(f"检查完成：{checked.tasks_checked:,} 个任务。请勿重复刷新。")
    except Exception as error:
        progress_bar.progress(0.0, text="检查失败 / Check failed")
        status_box.update(label="检查失败 / Check failed", state="error")
        detail.empty()
        st.error(f"检查失败 / Check failed: {error}")

result = st.session_state.get("check_result")
if result is not None:
    summary = result.summary()
    st.subheader("质量 Dashboard / Quality Dashboard")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    reviewer_rate = summary["reviewer_not_returned_rate"]
    col1.metric(
        "Reviewer 未打回率 / No-return rate",
        _format_percentage(reviewer_rate)
        if reviewer_rate is not None
        else "暂无 / N/A",
    )
    col2.metric(
        "Reviewer 检查覆盖率 / Coverage",
        _format_percentage(summary["reviewer_coverage_rate"]),
    )
    col3.metric(
        "Reviewer 已检查 / Reviewed",
        f"{summary['reviewer_checked_count']:,}",
    )
    col4.metric(
        "自动规则通过率 / Automated pass rate",
        _format_percentage(summary["hard_pass_rate"]),
    )
    col5.metric("错误任务 / Error tasks", f"{summary['tasks_with_errors']:,}")
    col6.metric("风险任务 / Warning tasks", f"{summary['tasks_with_warnings']:,}")
    st.caption(
        f"工具共检查 {summary['tasks_checked']:,} 个任务。Reviewer 未打回率"
        "=（accepted + fixed_and_accepted）÷（accepted + fixed_and_accepted + "
        "rejected）；Reviewer 检查覆盖率=Reviewer 已检查数÷工具检查任务数；"
        "自动规则通过率=无 error 的任务数÷工具检查任务数。"
    )
    if int(task_limit) > 0:
        st.caption(
            "当前设置了任务数量上限，Reviewer 检查覆盖率仅代表本次抽样范围；"
            "将“最多检查任务数”设为 0 后重新运行，才是整个导出文件的覆盖率。"
        )

    reviewer_checked = summary["reviewer_checked_count"]
    if reviewer_checked == 0:
        st.info(
            "暂无 Reviewer 最终审核记录；自动规则结果仍可正常使用。"
            " / No final reviewer actions found."
        )
    elif reviewer_checked < 30:
        st.warning(
            f"Reviewer 当前仅检查 {reviewer_checked:,} 个任务，样本量较小；"
            "解读未打回率时请同时关注检查数量。"
        )

    if result.issues_truncated:
        st.warning(
            "问题明细已达到保留上限；汇总计数仍完整。"
            " / Issue rows were truncated, while aggregate counts remain complete."
        )

    reviewer_rows = [
        {
            "状态 / Status": label,
            "任务数 / Tasks": result.reviewer_action_counts[action],
        }
        for action, label in (
            ("accepted", "直接接受 / Accepted"),
            ("fixed_and_accepted", "修正后接受 / Fixed and accepted"),
            ("rejected", "打回 / Rejected"),
        )
        if result.reviewer_action_counts[action] > 0
    ]
    severity_rows = [
        {"严重级别 / Severity": severity, "问题数 / Issues": count}
        for severity, count in (
            ("error", summary["error_count"]),
            ("warning", summary["warning_count"]),
            ("ignore", summary["ignore_count"]),
            ("info", summary["info_count"]),
        )
        if count > 0
    ]

    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.subheader("Reviewer 状态 / Reviewer status")
        if reviewer_rows:
            st.bar_chart(
                reviewer_rows,
                x="状态 / Status",
                y="任务数 / Tasks",
                use_container_width=True,
            )
        else:
            st.caption("暂无数据 / No data")
    with chart_right:
        st.subheader("严重级别分布 / Severity distribution")
        if severity_rows:
            st.bar_chart(
                severity_rows,
                x="严重级别 / Severity",
                y="问题数 / Issues",
                use_container_width=True,
            )
        else:
            st.caption("未发现问题 / No issues found")

    st.subheader("Top 10 自动规则问题 / Top 10 automated issues")
    issue_rows = [
        {"规则代码 / Rule": code, "问题数 / Issues": count}
        for code, count in result.issue_counts.most_common(10)
    ]
    if issue_rows:
        st.bar_chart(
            issue_rows,
            x="规则代码 / Rule",
            y="问题数 / Issues",
            use_container_width=True,
        )
        st.dataframe(issue_rows, width="stretch", hide_index=True)
    else:
        st.success("未发现自动规则问题 / No automated rule issues found.")

    st.subheader("数据指标 / Data metrics")
    metric_rows = [
        {"metric": key, "value": value}
        for key, value in result.metric_counts.most_common()
    ]
    st.dataframe(metric_rows, width="stretch", hide_index=True)

    st.subheader("问题明细 / Issue details")
    st.dataframe(
        [issue.to_dict() for issue in result.issues[:1_000]],
        width="stretch",
        hide_index=True,
    )
    if len(result.issues) > 1_000:
        st.caption("网页仅展示前 1,000 条，下载报告包含保留范围内的全部明细。")

    left, right = st.columns(2)
    left.download_button(
        "下载问题明细 CSV / Download CSV",
        data=issues_csv_bytes(result),
        file_name=f"{Path(result.source_name).stem}_qa_issues.csv",
        mime="text/csv",
    )
    right.download_button(
        "下载汇总 JSON / Download JSON",
        data=report_json_bytes(result),
        file_name=f"{Path(result.source_name).stem}_qa_summary.json",
        mime="application/json",
    )

st.divider()
st.caption(
    "说明：工具不会判断肉眼语义是否正确。15%–20% 轮廓偏差、动作含义、"
    "货架物品和手/背景误入仍需人工抽检。上传和检查过程中请不要刷新页面。"
)
