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
else:
    uploaded_file = st.file_uploader(
        "上传 Label Studio JSON 或 JSON.GZ",
        type=["json", "gz"],
    )
    st.info(
        "建议上传压缩后的 .json.gz，压缩文件上限为 500 MB。"
        "文件不会写入持久化存储。"
    )

if st.button("开始检查 / Run QA", type="primary"):
    status = st.empty()

    def update_progress(count: int) -> None:
        status.info(f"已检查 {count:,} 个任务 / Checked {count:,} tasks")

    try:
        if local_mode and source_mode.startswith("本地"):
            path = resolve_local_path(local_path)
            if not path.is_file():
                raise ValueError("找不到该文件，请检查路径和空格。")
            if not is_supported_filename(path.name):
                raise ValueError("请选择 .json 或 .json.gz 文件。")
            with open_task_stream(path) as stream:
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
            stream = uploaded_task_stream(uploaded_file, uploaded_file.name)
            try:
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
        st.session_state["check_result"] = checked
        status.success(f"检查完成：{checked.tasks_checked:,} 个任务")
    except Exception as error:
        status.empty()
        st.error(f"检查失败 / Check failed: {error}")

result = st.session_state.get("check_result")
if result is not None:
    summary = result.summary()
    st.subheader("结果概览 / Summary")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("已检查 / Checked", f"{summary['tasks_checked']:,}")
    col2.metric("硬规则通过率 / Pass rate", f"{summary['hard_pass_rate']:.1%}")
    col3.metric("错误任务 / Error tasks", f"{summary['tasks_with_errors']:,}")
    col4.metric("风险任务 / Warning tasks", f"{summary['tasks_with_warnings']:,}")

    if result.issues_truncated:
        st.warning(
            "问题明细已达到保留上限；汇总计数仍完整。"
            " / Issue rows were truncated, while aggregate counts remain complete."
        )

    st.subheader("问题分布 / Issue distribution")
    issue_rows = [
        {"code": code, "count": count}
        for code, count in result.issue_counts.most_common()
    ]
    st.dataframe(issue_rows, width="stretch", hide_index=True)

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
    "货架物品和手/背景误入仍需人工抽检。"
)
