# 标注质量门禁 / Annotation QA Checker

用于在上传或交付前检查 OmniTrack 与 Multiview 的 Label Studio JSON。支持本地运行和带共享密码的线上试点，不会在报告中输出标注员邮箱。

Checks OmniTrack and Multiview Label Studio JSON before upload or delivery. It supports local use and a password-protected online pilot. Annotator emails are excluded from reports.

## 安装与启动 / Install and run

需要 Python 3.9 或更高版本。

Python 3.9 or later is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
APP_LOCAL_MODE=true streamlit run app.py
```

浏览器打开终端显示的本地地址。支持 `.json` 和 `.json.gz`；首次验证可把任务上限设置为 100 或 1000。

Open the local URL shown in the terminal. Both `.json` and `.json.gz` are supported. For the first trial, set the task limit to 100 or 1,000.

## 压缩大文件 / Compress large files

线上版本建议上传 `.json.gz`，以降低上传时间和内存压力：

Use `.json.gz` online to reduce upload time and memory pressure:

```bash
gzip -k /path/to/export.json
```

`-k` 会保留原始 JSON。请只上传经过脱敏、且符合公司数据安全政策的文件。

`-k` keeps the original JSON. Upload only anonymized files allowed by company data policy.

## Streamlit Community Cloud 试点部署 / Pilot deployment

1. 将代码放入 GitHub 私有仓库，不要提交 `.streamlit/secrets.toml`。
2. 在 Streamlit Community Cloud 创建应用，入口文件选择 `app.py`。
3. 在应用的 Secrets 中添加共享密码：

1. Push the code to a private GitHub repository. Never commit `.streamlit/secrets.toml`.
2. Create the app in Streamlit Community Cloud and select `app.py`.
3. Add the shared password in the app Secrets:

```toml
APP_PASSWORD = "replace-with-a-strong-password"
```

线上试点支持最大 500 MB 的上传文件，但实际可处理大小还受云端内存和运行时限制。2.3 GB 原始 JSON 不应直接上传，请先压缩；如果压缩后仍过大，应改用内部对象存储方案。

The pilot allows uploads up to 500 MB, but practical size also depends on cloud memory and runtime limits. Do not upload a raw 2.3 GB JSON. Compress it first; if it remains too large, use an internal object-storage workflow.

共享密码只适合短期脱敏数据试点，不等同于正式的供应商账号、权限隔离和审计系统。

A shared password is suitable only for a short anonymized-data pilot. It is not a production vendor identity, isolation, or audit system.

## 当前检查项 / Current checks

OmniTrack：

- 双相机视频字段、有效标注、`ITEM1–ITEM7` 和 Barcode 标签。
- 关键帧顺序、重复帧、框坐标、位置突跳和面积突变。
- 每个 ITEM 一个 whole-clip action、action 枚举和商品类型冲突。
- Barcode 与 ITEM 关系完整性。

Multiview：

- 多相机图片字段、bbox 坐标、item/barcode 标签。
- moving 属性是否合法、是否存在孤立或重复属性。
- 跨视角关系是否引用有效 bbox、关系两端是否误在同一画面。

## 如何理解结果 / How to interpret results

- `error`：结构或逻辑明确违反规则，会计入硬规则不通过。
- `warning`：高风险信号，需要人工查看，不能直接判定标错。
- `info`：统计信息。

- `error`: a definite structural or logical rule violation.
- `warning`: a risk signal requiring human review.
- `info`: statistical information.

工具无法仅凭导出 JSON 判断轮廓是否偏离真实物体 15%–20%、动作语义是否正确、是否误框手/背景、货架物品是否应被排除。这些场景仍需人工抽检。

The export alone cannot prove polygon-to-object fit, action semantics, hand/background inclusion, or shelf-item relevance. These cases still require human review.

## 测试 / Test

```bash
pytest
```

真实数据验收建议：先检查 100 条，确认项目识别与问题类型合理，再逐步扩大到 1,000 条和全量，避免错误规则在超大文件上浪费运行时间。

For real-data validation, check 100 tasks first, then 1,000, and finally the full export after confirming project detection and issue categories.
