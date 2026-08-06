from __future__ import annotations

import hmac
import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


def is_local_mode() -> bool:
    return os.getenv("APP_LOCAL_MODE", "").strip().lower() in {"1", "true", "yes"}


def _configured_password() -> str:
    env_password = os.getenv("APP_PASSWORD", "")
    if env_password:
        return env_password
    try:
        return str(st.secrets.get("APP_PASSWORD", ""))
    except (FileNotFoundError, StreamlitSecretNotFoundError):
        return ""


def require_authentication() -> None:
    """Stop the app until a configured shared password is supplied."""
    if is_local_mode() or st.session_state.get("authenticated", False):
        return

    expected_password = _configured_password()
    st.title("标注质量门禁 / Annotation QA Checker")
    if not expected_password:
        st.error(
            "服务尚未配置 APP_PASSWORD，已拒绝公开访问。"
            " / APP_PASSWORD is not configured; public access is disabled."
        )
        st.stop()

    with st.form("login_form"):
        supplied_password = st.text_input(
            "访问密码 / Access password",
            type="password",
        )
        submitted = st.form_submit_button("登录 / Sign in", type="primary")

    if submitted:
        if hmac.compare_digest(supplied_password, expected_password):
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("密码错误 / Incorrect password")
    st.stop()
