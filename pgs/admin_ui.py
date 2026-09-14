import streamlit as st


_ADMIN_UI_CSS = """
<style>
.admin-shell {
    margin-bottom: 1rem;
    padding: 1.15rem 1.35rem;
    border-radius: 24px;
    background: rgba(255, 255, 255, 0.82);
    border: 1px solid rgba(12, 123, 179, 0.14);
    box-shadow: 0 18px 44px rgba(19, 62, 107, 0.10);
    backdrop-filter: blur(12px);
}
.admin-shell-title {
    margin: 0;
    color: #10233a;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.9rem;
    font-weight: 800;
}
.admin-shell-copy {
    margin: 0.4rem 0 0 0;
    color: #5f738b;
    font-size: 0.98rem;
    line-height: 1.6;
}
.admin-section {
    margin: 0.35rem 0 0.9rem 0;
    padding: 0.9rem 1rem;
    border-radius: 20px;
    background: rgba(247, 251, 255, 0.92);
    border: 1px solid rgba(23, 190, 187, 0.18);
    box-shadow: 0 12px 26px rgba(17, 70, 117, 0.08);
}
.admin-section-title {
    margin: 0;
    color: #10233a;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.08rem;
    font-weight: 700;
}
.admin-section-copy {
    margin: 0.3rem 0 0 0;
    color: #5f738b;
    font-size: 0.92rem;
    line-height: 1.55;
}
</style>
"""


def render_admin_shell(title: str, description: str) -> None:
    st.markdown(
        _ADMIN_UI_CSS
        + f"<div class='admin-shell'><h2 class='admin-shell-title'>{title}</h2>"
        + f"<p class='admin-shell-copy'>{description}</p></div>",
        unsafe_allow_html=True,
    )


def render_admin_section(title: str, description: str | None = None) -> None:
    copy_html = f"<p class='admin-section-copy'>{description}</p>" if description else ""
    st.markdown(
        f"<div class='admin-section'><h3 class='admin-section-title'>{title}</h3>{copy_html}</div>",
        unsafe_allow_html=True,
    )