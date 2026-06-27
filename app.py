from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
import streamlit as st
from pydantic import ValidationError

from core.models import PaperType, detect_paper_type
from core.settings import GraderConfig, MailConfig, app_settings
from core.storage import CSVStore
from modules.downloader import DownloadRequest, DownloadSource, PaperDownloader
from modules.grader import (
    GradingReport,
    QuestionResult,
    detect_handwriting_pages,
    grade_question,
    parse_grading_result,
    render_pages,
)
from modules.mailer import GoodNotesMailer, MailRequest
from modules.manager import DeleteRequest, PaperManager, ScoreUpdate
from modules.ms_parser import (
    PaperConfig,
    parse_mark_scheme,
)
from modules.page_segmenter import segment_questions, validate_regions
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
def submit_score_dialog() -> None:
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
    raw = col1.number_input(
        "Score Achieved", min_value=0.0, step=1.0,
        key=f"draft_raw_{selected_id}",
    )
    total = col2.number_input(
        "Total Marks", min_value=0.1, step=1.0, value=100.0,
        key=f"draft_total_{selected_id}",
    )

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
        value=_saved.sender_app_password.get_secret_value() if _saved and _saved.sender_app_password else "",
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

    st.divider()
    st.markdown("**Grader API (Qwen-VL)**")

    _grader_saved = GraderConfig.try_load()

    grader_api_key = st.text_input(
        "API Key",
        type="password",
        value=_grader_saved.api_key.get_secret_value() if _grader_saved else "",
        key="grader_api_key",
    )
    grader_base_url = st.text_input(
        "Base URL",
        value=_grader_saved.base_url if _grader_saved else "https://dashscope.aliyuncs.com/compatible-mode/v1",
        key="grader_base_url",
    )
    grader_model = st.text_input(
        "Model",
        value=_grader_saved.model if _grader_saved else "qwen3-vl-flash",
        key="grader_model",
    )

    grader_config: GraderConfig | None = None
    if grader_api_key:
        try:
            grader_config = GraderConfig(
                api_key=grader_api_key,
                base_url=grader_base_url,
                model=grader_model,
            )
            st.success("✅ Grader API config valid")
        except ValidationError as exc:
            st.error(fmt_validation_error(exc))

    if st.button("💾 Save grader credentials", disabled=grader_config is None):
        try:
            assert grader_config is not None
            grader_config.save_to_env()
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

tab_download, tab_manage, tab_analytics, tab_mark = st.tabs(
    ["📥 Download", "📋 Manage", "📊 Analytics", "✏️ Mark"]
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

    st.markdown(
        "<style>"
        "div[data-testid='stHorizontalBlock']"
        ":has([data-testid='stBaseButton-primary'])"
        "{gap:0!important}"
        " div[data-testid='stHorizontalBlock']"
        ":has([data-testid='stBaseButton-primary'])>div"
        "{padding-left:0!important;padding-right:0!important}"
        "</style>",
        unsafe_allow_html=True,
    )
    btn_col1, btn_col2, _ = st.columns([1, 1, 4])

    if btn_col1.button("⬇️ Download", type="primary"):
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

    if btn_col2.button("📝 Record"):
        if not paper_id:
            st.warning("Please enter a Paper ID.")
        else:
            downloader = PaperDownloader(store=store)
            result = downloader.record_only(paper_id)
            if not result.success:
                st.error(f"Record failed: {result.error}")
            else:
                st.success(f"✅ Recorded (no PDF): `{result.paper_id}`")

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
                                pct = record.percentage
                                st.markdown(
                                    f"**{record.score_raw}/"
                                    f"{record.score_total}**"
                                    f" ({pct:.1f}%)"
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

                            with bc3.popover("···"):
                                # ── Send to GoodNotes ──────────────────
                                _gn_disabled = mail_config is None or not record.qp_path
                                _gn_help = (
                                    "Configure SMTP in the sidebar first."
                                    if mail_config is None
                                    else "No QP file for this record."
                                    if not record.qp_path
                                    else None
                                )
                                if st.button(
                                    "📨 Send to GoodNotes",
                                    key=f"lgn_{record.paper_id}",
                                    disabled=_gn_disabled,
                                    help=_gn_help,
                                ):
                                    try:
                                        mail_req = MailRequest(
                                            paper_id=record.paper_id,
                                            qp_path=record.qp_path,
                                        )
                                    except ValidationError as exc:
                                        st.error(fmt_validation_error(exc))
                                        mail_req = None
                                    if mail_req is not None:
                                        with st.spinner("Sending…"):
                                            mailer = GoodNotesMailer(
                                                config=mail_config,  # type: ignore[arg-type]
                                                store=store,
                                            )
                                            mail_res = mailer.send(mail_req)
                                        if mail_res.success:
                                            st.success(
                                                f"✅ Sent to {mail_res.recipient}"
                                            )
                                            if mail_res.error:
                                                st.warning(mail_res.error)
                                        else:
                                            st.error(f"Failed: {mail_res.error}")

                                st.divider()

                                # ── Delete ─────────────────────────────
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

# ---------------------------------------------------------------------------
# Tab 4 — Mark (AI Grading)
# ---------------------------------------------------------------------------

with tab_mark:
    st.header("AI-Powered Grading")
    st.caption(
        "Parse a mark scheme, upload your answer paper, "
        "and let AI grade it question by question."
    )

    if grader_config is None:
        st.warning("Configure the Grader API credentials in the sidebar first.")
    else:
        # ── Step 1: Select / parse mark scheme ─────────────────
        st.subheader("Step 1 — Mark Scheme")

        ms_source = st.radio(
            "Mark scheme source",
            options=["From downloaded paper", "Upload PDF"],
            horizontal=True,
            key="ms_source",
        )

        ms_pdf_path: str | None = None
        paper_type: PaperType | None = None

        if ms_source == "From downloaded paper":
            try:
                all_records = store.load_all()
            except ValueError:
                all_records = []

            supported_records = [
                r for r in all_records
                if r.ms_path and detect_paper_type(r.paper_id) is not None
            ]

            if not supported_records:
                st.info(
                    "No supported papers with mark schemes found. "
                    "Download a math/further-math paper first, "
                    "or upload directly."
                )
            else:
                syllabus_codes = sorted(
                    {r.paper_id.split("_")[0] for r in supported_records}
                )
                syl_col, paper_col = st.columns([1, 3])
                selected_syllabus = syl_col.selectbox(
                    "Syllabus code",
                    options=syllabus_codes,
                    key="ms_syllabus_select",
                )

                filtered_records = sorted(
                    [
                        r for r in supported_records
                        if r.paper_id.startswith(f"{selected_syllabus}_")
                    ],
                    key=lambda r: r.paper_id,
                )

                if not filtered_records:
                    st.info("No papers found for this syllabus code.")
                else:
                    ms_paper = paper_col.selectbox(
                        "Select paper",
                        options=[r.paper_id for r in filtered_records],
                        key="ms_paper_select",
                    )
                    target = next(
                        (r for r in filtered_records if r.paper_id == ms_paper),
                        None,
                    )
                    if target:
                        ms_pdf_path = target.ms_path
                        paper_type = detect_paper_type(target.paper_id)
        else:
            uploaded_ms = st.file_uploader(
                "Upload Mark Scheme PDF",
                type=["pdf"],
                key="ms_upload",
            )
            if uploaded_ms is not None:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                tmp.write(uploaded_ms.read())
                tmp.flush()
                ms_pdf_path = tmp.name
                paper_type = PaperType.MATH

        start_page = st.number_input(
            "Mark scheme content starts at page",
            min_value=1,
            value=6,
            help=(
                "CIE mark schemes typically have headers "
                "on pages 1-5. Content starts on page 6."
            ),
            key="ms_start_page",
        )

        can_parse = ms_pdf_path and paper_type
        if can_parse and st.button(
            "🔍 Parse Mark Scheme", type="primary",
        ):
            progress_bar = st.progress(0, text="Parsing mark scheme via AI…")

            def _on_progress(batch: int, total: int) -> None:
                progress_bar.progress(
                    batch / total,
                    text=f"Processing batch {batch}/{total}…",
                )

            try:
                paper_config = parse_mark_scheme(
                    ms_pdf_path,
                    paper_type=paper_type,
                    grader_config=grader_config,
                    start_page=start_page,
                    on_progress=_on_progress,
                )
                progress_bar.progress(1.0, text="Done!")
                st.session_state["paper_config"] = paper_config
                st.session_state["paper_type"] = paper_type
                st.session_state.pop("deleted_questions", None)

                st.success(
                    f"Parsed **{paper_config.paper_id}** — "
                    f"{len(paper_config.questions)} questions, "
                    f"{paper_config.total_marks} total marks"
                )
            except Exception as exc:
                st.error(
                    f"Failed to parse mark scheme: {exc}"
                )

        # Show parsed config
        if "paper_config" in st.session_state:
            pc: PaperConfig = st.session_state["paper_config"]
            n_q = len(pc.questions)
            with st.expander(
                f"Parsed: {pc.paper_id} ({n_q} questions)",
                expanded=False,
            ):
                for qid, qcfg in pc.questions.items():
                    st.markdown(
                        f"**{qid}** — {qcfg.max_marks} marks"
                    )
                    st.code(qcfg.mark_scheme, language=None)

            # ── Step 2: Upload answer paper ─────────────────────
            st.divider()
            st.subheader("Step 2 — Answer Paper")

            uploaded_answer = st.file_uploader(
                "Upload annotated answer paper (PDF from GoodNotes)",
                type=["pdf"],
                key="answer_upload",
            )

            if uploaded_answer is not None:
                answer_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                answer_tmp.write(uploaded_answer.read())
                answer_tmp.flush()
                st.session_state["answer_pdf_path"] = answer_tmp.name
                st.session_state.pop("auto_pages_done", None)

            if "answer_pdf_path" in st.session_state:
                answer_doc = fitz.open(st.session_state["answer_pdf_path"])
                total_pages = len(answer_doc)
                hw_pages = detect_handwriting_pages(answer_doc)

                # Auto-detect question→page mapping
                auto_pages: dict[str, str] = {}
                if "auto_pages_done" not in st.session_state:
                    q_ids = list(pc.questions.keys())
                    regions = segment_questions(answer_doc, q_ids)
                    matched, unmatched = validate_regions(
                        regions, q_ids
                    )
                    for region in regions:
                        page_nums = sorted(
                            {c.page_idx + 1 for c in region.clips}
                        )
                        auto_pages[region.question_id] = ",".join(
                            str(p) for p in page_nums
                        )
                    st.session_state["auto_pages"] = auto_pages
                    st.session_state["auto_pages_matched"] = matched
                    st.session_state["auto_pages_unmatched"] = unmatched
                    st.session_state["auto_pages_done"] = True
                else:
                    auto_pages = st.session_state.get("auto_pages", {})

                answer_doc.close()

                auto_matched = st.session_state.get(
                    "auto_pages_matched", []
                )
                auto_unmatched = st.session_state.get(
                    "auto_pages_unmatched", []
                )
                info_parts = [
                    f"PDF has **{total_pages}** pages.",
                    f"Handwriting on: **{hw_pages or 'none'}**.",
                ]
                if auto_matched:
                    info_parts.append(
                        f"Auto-detected **{len(auto_matched)}"
                        f"/{len(auto_matched) + len(auto_unmatched)}** "
                        "questions."
                    )
                st.info(" ".join(info_parts))
                if auto_unmatched:
                    st.warning(
                        f"Could not auto-detect: {', '.join(auto_unmatched)}"
                    )

                # Page assignment per question
                st.markdown("**Assign pages to questions:**")
                page_assignments: dict[str, list[int]] = {}

                deleted_qs: set[str] = st.session_state.get(
                    "deleted_questions", set()
                )
                q_items = [
                    (qid, qcfg) for qid, qcfg in pc.questions.items()
                    if qid not in deleted_qs
                ]

                cols_per_row = 3
                for row_start in range(0, len(q_items), cols_per_row):
                    cols = st.columns(cols_per_row)
                    chunk = q_items[row_start:row_start + cols_per_row]
                    for col_idx, (qid, qcfg) in enumerate(chunk):
                        with cols[col_idx]:
                            input_col, del_col = st.columns(
                                [5, 1], vertical_alignment="bottom",
                            )
                            with input_col:
                                default_val = auto_pages.get(qid, "")
                                pages_str = st.text_input(
                                    f"{qid} ({qcfg.max_marks}m)",
                                    value=default_val,
                                    placeholder="e.g. 2,3",
                                    key=f"pages_{qid}",
                                    help=(
                                        "Comma-separated page numbers "
                                        "(1-indexed)"
                                    ),
                                )
                            with del_col:
                                if st.button(
                                    "✕", key=f"del_q_{qid}",
                                    help=f"Remove {qid}",
                                ):
                                    dels = st.session_state.get(
                                        "deleted_questions", set()
                                    )
                                    dels.add(qid)
                                    st.session_state["deleted_questions"] = dels
                                    st.rerun()
                            if pages_str.strip():
                                try:
                                    pages = [
                                        int(p.strip())
                                        for p in pages_str.split(",")
                                        if p.strip()
                                    ]
                                    page_assignments[qid] = pages
                                except ValueError:
                                    st.error(
                                        f"Invalid page numbers for {qid}"
                                    )

                # ── Step 3: Grade ─────────────────────────────────
                st.divider()
                st.subheader("Step 3 — Grade")

                # Thinking mode toggle
                enable_thinking = st.toggle(
                    "Enable thinking mode",
                    value=grader_config.enable_thinking,
                    key="mark_thinking_toggle",
                    help=(
                        "Let the model reason step-by-step "
                        "before grading (slower but more accurate)"
                    ),
                )

                questions_to_grade = st.multiselect(
                    "Questions to grade",
                    options=list(pc.questions.keys()),
                    default=list(page_assignments.keys()),
                    key="grade_questions",
                )

                can_grade = (
                    questions_to_grade
                    and all(q in page_assignments for q in questions_to_grade)
                )

                if not can_grade and questions_to_grade:
                    missing = [
                        q for q in questions_to_grade
                        if q not in page_assignments
                    ]
                    st.warning(f"Assign pages to: {', '.join(missing)}")

                if st.button(
                    "🚀 Start Grading", type="primary", disabled=not can_grade
                ):
                    # Apply thinking toggle to a copy of grader config
                    grade_cfg = GraderConfig(
                        api_key=grader_config.api_key.get_secret_value(),
                        base_url=grader_config.base_url,
                        model=grader_config.model,
                        dpi=grader_config.dpi,
                        enable_thinking=enable_thinking,
                    )

                    answer_doc = fitz.open(st.session_state["answer_pdf_path"])
                    results: list[QuestionResult] = []
                    total_score = 0
                    total_max = 0

                    progress = st.progress(0, text="Grading…")
                    for i, qid in enumerate(questions_to_grade):
                        progress.progress(
                            (i) / len(questions_to_grade),
                            text=f"Grading {qid}…",
                        )
                        qcfg = pc.questions[qid]
                        pages = page_assignments[qid]
                        images = render_pages(answer_doc, pages, dpi=grade_cfg.dpi)

                        try:
                            raw = grade_question(
                                config=grade_cfg,
                                images=images,
                                question_id=qid,
                                mark_scheme=qcfg.mark_scheme,
                                max_marks=qcfg.max_marks,
                                paper_type=st.session_state.get(
                                    "paper_type", PaperType.MATH
                                ),
                            )
                            grade_result = parse_grading_result(raw)
                            results.append(grade_result)
                            total_score += grade_result.total
                            total_max += grade_result.max
                        except Exception as exc:
                            st.error(f"Failed to grade {qid}: {exc}")

                    progress.progress(1.0, text="Done!")
                    answer_doc.close()

                    # Save results to temp JSON for two-phase persistence
                    report = GradingReport(
                        results=results,
                        total_score=total_score,
                        total_max=total_max,
                    )
                    tmp_result = tempfile.NamedTemporaryFile(
                        delete=False, suffix=".json", mode="w", encoding="utf-8",
                    )
                    tmp_result.write(report.model_dump_json(indent=2))
                    tmp_result.flush()
                    tmp_result.close()

                    for key in list(st.session_state.keys()):
                        if key.startswith("score_override_"):
                            del st.session_state[key]

                    st.session_state["grading_results"] = results
                    st.session_state["grading_total"] = (total_score, total_max)
                    st.session_state["score_overrides"] = {
                        r.question: r.total for r in results
                    }
                    st.session_state["grading_temp_path"] = tmp_result.name
                    st.session_state["grading_confirmed"] = False

                # ── Results display ─────────────────────────────
                if "grading_results" in st.session_state:
                    st.divider()
                    st.subheader("Results")

                    grading_results: list[QuestionResult] = (
                        st.session_state["grading_results"]
                    )

                    if "score_overrides" not in st.session_state:
                        st.session_state["score_overrides"] = {
                            r.question: r.total for r in grading_results
                        }
                    _overrides = st.session_state["score_overrides"]

                    score = sum(
                        _overrides.get(r.question, r.total)
                        for r in grading_results
                    )
                    max_score = sum(r.max for r in grading_results)
                    pct = (score / max_score * 100) if max_score > 0 else 0

                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric("Total Score", f"{score}/{max_score}")
                    mc2.metric("Percentage", f"{pct:.1f}%")
                    mc3.metric("Questions Graded", len(grading_results))

                    def _on_score_change(question: str) -> None:
                        st.session_state["score_overrides"][question] = (
                            st.session_state[f"score_override_{question}"]
                        )

                    for result in grading_results:
                        _ov = _overrides.get(result.question, result.total)
                        exp_col, adj_col = st.columns(
                            [5, 1], vertical_alignment="top",
                        )
                        with exp_col:
                            with st.expander(
                                f"{result.question}"
                                f" — {_ov}/{result.max}",
                                expanded=True,
                            ):
                                for m in result.marks:
                                    icon = (
                                        "✅" if m.awarded else "❌"
                                    )
                                    st.markdown(
                                        f"{icon} **{m.code}**"
                                        f": {m.reason}"
                                    )
                                if result.comment:
                                    st.info(f"💬 {result.comment}")
                        with adj_col:
                            st.number_input(
                                "Adjust",
                                min_value=0,
                                max_value=result.max,
                                value=_ov,
                                key=f"score_override_{result.question}",
                                on_change=_on_score_change,
                                args=(result.question,),
                            )

                    # Two-phase persistence: Confirm & Log
                    if not st.session_state.get("grading_confirmed", False):
                        st.divider()
                        st.caption("Review the results above. Click below to log the score to your records.")
                        if st.button("✅ Confirm & Log Score", type="primary"):
                            # Find the paper record and update its score
                            try:
                                records = store.load_all()
                                # Try to match paper_id from the parsed config
                                paper_id_match = None
                                if ms_source == "From downloaded paper" and "ms_paper_select" in st.session_state:
                                    paper_id_match = st.session_state.get("ms_paper_select")

                                if paper_id_match:
                                    target_rec = next((r for r in records if r.paper_id == paper_id_match), None)
                                    if target_rec:
                                        updated = target_rec.model_copy(update={
                                            "score_raw": float(score),
                                            "score_total": float(max_score),
                                            "status": "Completed",
                                        })
                                        store.update(updated)
                                        st.session_state["grading_confirmed"] = True
                                        st.success(f"Score {score}/{max_score} logged for `{paper_id_match}`!")
                                        # Clean up temp file
                                        temp_path = st.session_state.get("grading_temp_path")
                                        if temp_path:
                                            Path(temp_path).unlink(missing_ok=True)
                                    else:
                                        st.warning("Could not find matching paper record to update.")
                                else:
                                    st.info(f"Score: {score}/{max_score} ({pct:.1f}%). Use 'Submit Score' to log to a specific paper.")
                                    st.session_state["grading_confirmed"] = True
                            except Exception as exc:
                                st.error(f"Failed to log score: {exc}")
                    else:
                        st.success("Score has been logged.")