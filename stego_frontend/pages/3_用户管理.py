# -*- coding: utf-8 -*-
"""Superuser-only user management page."""
import streamlit as st

from stego_frontend.modules import auth


def _fetch_users():
    result = auth.api_request("GET", "/users")
    if not result["ok"]:
        st.error(f"获取用户列表失败：{result['error']}")
        return []
    data = result["data"]
    return data if isinstance(data, list) else []


def _render_user_table(users):
    keyword = st.text_input("搜索用户名/学号/邮箱", "")
    if keyword:
        k = keyword.lower()
        users = [
            u
            for u in users
            if k in str(u.get("username", "")).lower()
            or k in str(u.get("student_id", "")).lower()
            or k in str(u.get("email", "")).lower()
        ]
    st.caption(f"共 {len(users)} 个用户")
    st.dataframe(
        users,
        width="stretch",
        hide_index=True,
    )


def _render_create_user():
    st.subheader("创建用户")
    with st.form("create_user_form", clear_on_submit=True):
        username = st.text_input("用户名")
        password = st.text_input("初始密码", type="password")
        email = st.text_input("邮箱")
        student_id = st.text_input("学号")
        major = st.text_input("专业")
        grade = st.text_input("年级")
        is_staff = st.checkbox("允许后台登录(is_staff)", value=False)
        is_superuser = st.checkbox("超级管理员(is_superuser)", value=False)
        is_active = st.checkbox("启用账户(is_active)", value=True)
        submit = st.form_submit_button("创建用户", width="stretch")

    if submit:
        payload = {
            "username": username,
            "password": password,
            "email": email,
            "student_id": student_id or None,
            "major": major,
            "grade": grade,
            "is_staff": is_staff,
            "is_superuser": is_superuser,
            "is_active": is_active,
        }
        result = auth.api_request("POST", "/users", json_data=payload)
        if result["ok"]:
            st.success("创建成功")
            st.rerun()
        st.error(f"创建失败：{result['error']}")


def _render_edit_delete(users):
    st.subheader("编辑/删除用户")
    if not users:
        st.info("暂无可编辑用户")
        return

    options = {f"{u.get('id')} - {u.get('username')}": u for u in users}
    selected_key = st.selectbox("选择用户", list(options.keys()))
    selected = options[selected_key]

    with st.form("edit_user_form", clear_on_submit=False):
        username = st.text_input("用户名", value=selected.get("username", ""))
        password = st.text_input("重置密码（留空则不修改）", type="password")
        email = st.text_input("邮箱", value=selected.get("email", ""))
        student_id = st.text_input("学号", value=selected.get("student_id") or "")
        major = st.text_input("专业", value=selected.get("major", ""))
        grade = st.text_input("年级", value=selected.get("grade", ""))
        is_staff = st.checkbox("is_staff", value=bool(selected.get("is_staff")))
        is_superuser = st.checkbox("is_superuser", value=bool(selected.get("is_superuser")))
        is_active = st.checkbox("is_active", value=bool(selected.get("is_active", True)))
        submit_update = st.form_submit_button("保存修改", width="stretch")

    if submit_update:
        payload = {
            "username": username,
            "email": email,
            "student_id": student_id or None,
            "major": major,
            "grade": grade,
            "is_staff": is_staff,
            "is_superuser": is_superuser,
            "is_active": is_active,
        }
        if password:
            payload["password"] = password
        result = auth.api_request("PATCH", f"/users/{selected['id']}", json_data=payload)
        if result["ok"]:
            st.success("更新成功")
            st.rerun()
        st.error(f"更新失败：{result['error']}")

    st.divider()
    confirm = st.checkbox("确认删除该用户（不可恢复）", value=False)
    if st.button("删除用户", type="primary", width="stretch", disabled=not confirm):
        result = auth.api_request("DELETE", f"/users/{selected['id']}")
        if result["ok"]:
            st.success("删除成功")
            st.rerun()
        st.error(f"删除失败：{result['error']}")


def main() -> None:
    st.set_page_config(
        page_title="\u7528\u6237\u7ba1\u7406",
        page_icon="\U0001f465",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    auth.require_login()
    user = st.session_state.get("current_user") or {}
    if not user.get("is_superuser"):
        st.error("无权限访问：仅超级管理员可以进入用户管理。")
        st.stop()

    st.title("\u7528\u6237\u7ba1\u7406")
    users = _fetch_users()
    _render_user_table(users)

    col1, col2 = st.columns(2)
    with col1:
        _render_create_user()
    with col2:
        _render_edit_delete(users)


if __name__ == "__main__":
    main()
