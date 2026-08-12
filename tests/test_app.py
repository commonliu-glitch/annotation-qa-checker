from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_public_app_requires_password(monkeypatch) -> None:
    monkeypatch.delenv("APP_LOCAL_MODE", raising=False)
    monkeypatch.setenv("APP_PASSWORD", "pilot-secret")

    app = AppTest.from_file("app.py").run()
    assert app.text_input[0].label == "访问密码 / Access password"
    assert not app.selectbox

    app.text_input[0].set_value("pilot-secret")
    app.button[0].click().run()

    assert app.selectbox[0].label == "项目类型 / Project type"
    assert any(".json.gz" in message.value for message in app.info)


def test_app_runs_real_multiview_sample(monkeypatch) -> None:
    monkeypatch.setenv("APP_LOCAL_MODE", "true")
    sample_path = (
        "/Users/common/Downloads/export/2026-7-21/"
        "multiview-detection-batch26-dedup-at-2026-07-21-05-46-0692f7c6.json"
    )
    if not Path("/Users/common/Downloads/export").exists():
        return

    app = AppTest.from_file("app.py").run()
    app.text_input[0].set_value(sample_path)
    app.number_input[0].set_value(100)
    app.button[0].click().run(timeout=30)

    assert not app.error
    assert app.metric[0].label == "Reviewer 未打回率 / No-return rate"
    assert app.metric[1].label == "Reviewer 检查覆盖率 / Coverage"
    assert app.metric[2].label == "Reviewer 已检查 / Reviewed"
    assert app.metric[3].value == "93.0%"
    assert app.metric[4].value == "7"
    assert app.metric[5].value == "6"


def test_dashboard_handles_missing_reviewer_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_LOCAL_MODE", "true")
    sample_path = tmp_path / "unreviewed.json"
    sample_path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "data": {"imageA": "a", "imageB": "b"},
                    "annotations": [
                        {
                            "id": 1,
                            "updated_at": "2026-01-01",
                            "result": [
                                {
                                    "id": "bbox-1",
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
                    ],
                }
            ]
        )
    )

    app = AppTest.from_file("app.py").run()
    app.text_input[0].set_value(str(sample_path))
    app.button[0].click().run()

    assert not app.error
    assert app.metric[0].value == "暂无 / N/A"
    assert app.metric[1].value == "0.0%"
    assert app.metric[2].value == "0"
    assert app.metric[3].value == "100.0%"
    assert any("暂无 Reviewer" in message.value for message in app.info)
