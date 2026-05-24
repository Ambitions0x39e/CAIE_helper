from __future__ import annotations

import streamlit as st
from pydantic import ValidationError

from core.settings import AppSettings, MailConfig, app_settings
from core.storage import CSVStore
from modules.downloader import DownloadRequest, DownloadSource, PaperDownloader
from modules.mailer import GoodNotesMailer, MailRequest
from modules.manager import DeleteRequest, PaperManager, ScoreUpdate
from modules.visualizer import PaperVisualizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_validation_error(exc: ValidationError) -> str:
    """
    Convert a Pydantic ValidationError into a clean human-readable string.
    Example output:
        • paper_id: must match '<subject>_<session>_<component>_<variant>'
        • score_raw: value cannot be negative
    """
    lines = []
    for err in exc.errors():
        field = " → ".join(str(loc) for loc in err["loc"]) if err["loc"] else "input"
        msg = err["msg"].removeprefix("Value error, ").removeprefix("value error, ")
        lines.append(f"• **{field}**: {msg}")
    return "\n\n".join(lines)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="CIE Helper",
    page_icon="📄",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Initialise filesystem on startup
# ---------------------------------------------------------------------------

app_settings.init_dirs()
store = CSVStore()


# ---------------------------------------------------------------------------
# Submit Score Dialog (global gadget)
# ---------------------------------------------------------------------------


@st.dialog("Submit Score")
def submit_score_dialog():
    """Floating score submission widget — triggered from the fixed top-right button."""
    try:
        all_records = store.load_all()
    except ValueError as exc:
        st.error(f"Failed to load data: {exc}")
        return

    pending_ids = [r.paper_id for r in all_records if r.status == "Pending"]
    if not pending_ids:
        st.info("No pending papers — all done! 🎉")
        return

    selected_id = st.selectbox("Select Paper", options=pending_ids)
    col1, col2 = st.columns(2)
    raw = col1.number_input("Score Achieved", min_value=0.0, step=1.0)
    total = col2.number_input("Total Marks", min_value=0.1, step=1.0, value=100.0)

    if st.button("✅ Submit", type="primary", width="stretch"):
        try:
            update = ScoreUpdate(
                paper_id=selected_id,
                score_raw=raw,
                score_total=total,
            )
        except ValidationError as exc:
            st.error(fmt_validation_error(exc))
        else:
            manager = PaperManager(store=store)
            result = manager.submit_score(update)
            if result.success:
                st.success(f"Score recorded for `{result.paper_id}`!")
                st.rerun()
            else:
                st.error(f"Failed to save score: {result.error}")


# ---------------------------------------------------------------------------
# Sidebar — SMTP config + Quick Actions
# ---------------------------------------------------------------------------

# Try loading saved credentials from .env on every page load
_saved = MailConfig.try_load()

with st.sidebar:
    st.title("⚙️ Settings")
    st.markdown("**SMTP / GoodNotes**")

    smtp_server = st.text_input(
        "SMTP Server",
        value=_saved.smtp_server if _saved else "smtp.gmail.com",
    )
    smtp_port = st.number_input(
        "SMTP Port",
        value=_saved.smtp_port if _saved else 465,
        min_value=1,
        max_value=65535,
    )
    sender_email = st.text_input(
        "Sender Email",
        value=str(_saved.sender_email) if _saved else "",
    )
    sender_password = st.text_input(
        "App Password",
        type="password",
        value=_saved.sender_app_password.get_secret_value() if _saved else "",
    )
    goodnotes_email = st.text_input(
        "GoodNotes Import Email",
        value=str(_saved.goodnotes_email) if _saved else "",
    )

    mail_config: MailConfig | None = None
    if all([smtp_server, sender_email, sender_password, goodnotes_email]):
        try:
            mail_config = MailConfig(
                smtp_server=smtp_server,
                smtp_port=int(smtp_port),
                sender_email=sender_email,        # type: ignore[arg-type]
                sender_app_password=sender_password,
                goodnotes_email=goodnotes_email,  # type: ignore[arg-type]
            )
            st.success("✅ SMTP config valid")
        except ValidationError as exc:
            st.error(fmt_validation_error(exc))

    st.divider()
    if st.button("💾 Save credentials to .env", disabled=mail_config is None):
        try:
            mail_config.save_to_env()  # type: ignore[union-attr]
            st.success("Saved to .env")
        except OSError as exc:
            st.error(f"Could not write .env: {exc}")


# ---------------------------------------------------------------------------
# Submit Score — fixed top-right button
# ---------------------------------------------------------------------------

if st.button("✏️ Submit Score", type="primary", key="score_trigger"):
    submit_score_dialog()

st.markdown(
    """<style>
    /* Pin the Submit Score button to the top-right header area */
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stElementContainer"]:first-child {
        position: fixed;
        top: 1%;
        right: 6.5%;
        z-index: 999991;
        width: auto;
    }
    </style>""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_download, tab_manage, tab_analytics = st.tabs(
    ["📥 Download", "📋 Manage", "📊 Analytics"]
)

# ---------------------------------------------------------------------------
# Tab 1 — Download
# ---------------------------------------------------------------------------

with tab_download:
    st.header("Download Past Paper")

    # Single-row two-column label bar: left = "Paper ID", right = source control
    label_col, src_col = st.columns([3, 1], vertical_alignment="bottom")
    paper_id = label_col.text_input(
        "Paper ID",
        placeholder="9702_s23_qp_11",
        help="Must follow the format: <subject>_<session>_qp_<variant>",
    )
    source: DownloadSource = src_col.segmented_control(
        "Source",
        options=["CIEFrank", "PapaCambridge"],
        default="CIEFrank",
        key="dl_source",
        label_visibility="visible",
    )  # type: ignore[assignment]

    if st.button("⬇️ Download", type="primary"):
        if not paper_id:
            st.warning("Please enter a Paper ID.")
        else:
            try:
                request = DownloadRequest(paper_id=paper_id, source=source)
            except ValidationError as exc:
                st.error(fmt_validation_error(exc))
                request = None

            if request is not None:
                with st.spinner("Downloading QP and MS…"):
                    downloader = PaperDownloader(store=store)
                    result = downloader.download(request)

                if not result.success:
                    st.error(f"Download failed: {result.error}")
                else:
                    st.success(f"✅ Downloaded: `{result.paper_id}`")
                    st.caption(f"QP → `{result.qp_path}`")
                    st.caption(f"MS → `{result.ms_path}`")

                    # Store the downloaded paper_id so the Send button can reference it
                    st.session_state["last_downloaded_id"] = result.paper_id
                    st.session_state["last_downloaded_qp"] = result.qp_path

    # Send to GoodNotes — only shown after a successful download
    if "last_downloaded_id" in st.session_state:
        st.divider()
        col_info, col_btn = st.columns([3, 1])
        col_info.caption(
            f"Ready to send: `{st.session_state['last_downloaded_id']}`"
        )

        with col_btn:
            send_disabled = mail_config is None
            if st.button(
                "📨 Send to GoodNotes",
                disabled=send_disabled,
                help="Configure SMTP in the sidebar first." if send_disabled else None,
            ):
                try:
                    mail_request = MailRequest(
                        paper_id=st.session_state["last_downloaded_id"],
                        qp_path=st.session_state["last_downloaded_qp"] or "",
                    )
                except ValidationError as exc:
                    st.error(fmt_validation_error(exc))
                    mail_request = None

                if mail_request is not None:
                    with st.spinner("Sending to GoodNotes…"):
                        mailer = GoodNotesMailer(config=mail_config, store=store)
                        mail_result = mailer.send(mail_request)

                    if mail_result.success:
                        st.success(f"✅ Sent to {mail_result.recipient}")
                        if mail_result.error:
                            st.warning(f"Note: {mail_result.error}")
                        # Clear session state after successful send
                        del st.session_state["last_downloaded_id"]
                        del st.session_state["last_downloaded_qp"]
                    else:
                        st.error(f"Email failed: {mail_result.error}")

# ---------------------------------------------------------------------------
# Tab 2 — Manage
# ---------------------------------------------------------------------------

with tab_manage:
    st.header("Manage Papers")

    try:
        all_records = store.load_all()
    except ValueError as exc:
        st.error(f"Failed to load data.csv:\n{exc}")
        all_records = None

    if all_records is not None and not all_records:
        st.info("No papers downloaded yet. Use the Download tab to get started.")
    elif all_records:
        manager = PaperManager(store=store)

        view = st.segmented_control(
            "View",
            options=["Database", "List"],
            default="Database",
            key="manage_view",
        )

        # ── Database view ────────────────────────────────────────
        if view is None or view == "Database":
            df = store.to_dataframe(all_records)
            st.dataframe(df, width="stretch", hide_index=True)

            st.subheader("Open PDF Locally")
            all_ids = [r.paper_id for r in all_records]
            open_id = st.selectbox(
                "Select Paper", options=all_ids, key="open_select"
            )
            col_qp, col_ms = st.columns(2)

            target = next(
                (r for r in all_records if r.paper_id == open_id), None
            )
            if target:
                if col_qp.button("📄 Open QP"):
                    res = manager.open_pdf(target.qp_path)
                    if not res.success:
                        st.error(res.error)

                if col_ms.button("📄 Open MS"):
                    res = manager.open_pdf(target.ms_path)
                    if not res.success:
                        st.error(res.error)

        # ── List view ────────────────────────────────────────────
        elif view == "List":
            hide_completed = st.toggle("Hide completed", value=True)

            filtered = all_records
            if hide_completed:
                filtered = [r for r in all_records if r.status == "Pending"]

            if not filtered:
                st.info("No papers match the current filter.")
            else:
                for record in filtered:
                    with st.container(border=True):
                        col_info, col_score, col_actions = st.columns(
                            [3, 2, 2], vertical_alignment="center"
                        )

                        with col_info:
                            icon = (
                                "✅" if record.status == "Completed" else "⏳"
                            )
                            st.markdown(f"**{icon} {record.paper_id}**")
                            if record.timestamp:
                                st.caption(
                                    record.timestamp.strftime(
                                        "%Y-%m-%d %H:%M UTC"
                                    )
                                )

                        with col_score:
                            if (
                                record.status == "Completed"
                                and record.percentage is not None
                            ):
                                st.markdown(
                                    f"**{record.score_raw}/{record.score_total}** ({record.percentage:.1f}%)"
                                )
                            else:
                                st.caption("Pending")

                        with col_actions:
                            bc1, bc2, bc3 = st.columns(3)
                            if bc1.button(
                                "Open QP", key=f"lqp_{record.paper_id}"
                            ):
                                res = manager.open_pdf(record.qp_path)
                                if not res.success:
                                    st.error(res.error)
                            if bc2.button(
                                "Open MS", key=f"lms_{record.paper_id}"
                            ):
                                res = manager.open_pdf(record.ms_path)
                                if not res.success:
                                    st.error(res.error)

                            with bc3.popover("🗑️"):
                                st.caption(
                                    f"Delete **{record.paper_id}**?"
                                )
                                del_files = st.checkbox(
                                    "Delete files too",
                                    key=f"ldf_{record.paper_id}",
                                )
                                if st.button(
                                    "Confirm",
                                    key=f"ldel_{record.paper_id}",
                                    type="primary",
                                ):
                                    try:
                                        del_req = DeleteRequest(
                                            paper_id=record.paper_id,
                                            delete_local_files=del_files,
                                        )
                                    except ValidationError as exc:
                                        st.error(
                                            fmt_validation_error(exc)
                                        )
                                    else:
                                        del_res = manager.delete(del_req)
                                        if del_res.success:
                                            st.rerun()
                                        else:
                                            st.error(del_res.error)

# ---------------------------------------------------------------------------
# Tab 3 — Analytics
# ---------------------------------------------------------------------------

with tab_analytics:
    try:
        all_records = store.load_all()
    except ValueError as exc:
        st.error(f"Failed to load data.csv:\n{exc}")
        all_records = None

    if all_records is not None:
        visualizer = PaperVisualizer(records=all_records)
        visualizer.render()