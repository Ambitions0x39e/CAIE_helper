from __future__ import annotations

import re
import tempfile
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from core.gt_parser import GradeThreshold, GTParser
from core.settings import app_settings
from core.storage import CSVStore
from modules.downloader import DownloadRequest, DownloadSource, PaperDownloader

st.set_page_config(
    page_title="CIE Helper — GT Checker",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 Grade Threshold Checker")
st.caption(
    "Download a GT, pick your option, bulk-download papers, "
    "enter scores, see your grade."
)

app_settings.init_dirs()
store = CSVStore()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_validation_error(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        field = " → ".join(str(loc) for loc in err["loc"]) if err["loc"] else "input"
        msg = err["msg"].removeprefix("Value error, ").removeprefix("value error, ")
        lines.append(f"• **{field}**: {msg}")
    return "\n\n".join(lines)


def _session_from_filename(name: str) -> str:
    """Extract session string from GT filename e.g. '9231_s25_gt' → 's25'."""
    match = re.search(r"_(s|w|m)(\d{2})_", name)
    return f"{match.group(1)}{match.group(2)}" if match else ""


def _grade_badge(grade: str) -> str:
    colours = {
        "A*": "🟣", "A": "🟢", "B": "🔵",
        "C": "🟡", "D": "🟠", "E": "🔴", "U": "⚫",
    }
    return f"{colours.get(grade, '⚪')} **{grade}**"


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "gt_doc" not in st.session_state:
    st.session_state["gt_doc"] = None
if "selected_option" not in st.session_state:
    st.session_state["selected_option"] = None
if "dl_results" not in st.session_state:
    st.session_state["dl_results"] = {}   # component → success
if "scores" not in st.session_state:
    st.session_state["scores"] = {}      # component → raw score


# ---------------------------------------------------------------------------
# Step 1 — Load GT
# ---------------------------------------------------------------------------

st.subheader("Step 1 — Load Grade Threshold Document")

col_file, col_manual = st.columns([1, 1])

with col_file:
    st.markdown("**Option A — Upload PDF**")
    uploaded = st.file_uploader(
        "Upload GT PDF", type=["pdf"], label_visibility="collapsed"
    )

with col_manual:
    st.markdown("**Option B — Download from site**")
    gt_filename = st.text_input(
        "GT filename (without .pdf)",
        placeholder="9231_s25_gt",
        help="Will fetch from cie.fraft.cn/obj/common/Fetch/redir/<filename>.pdf",
    )
    if st.button("⬇️ Fetch GT PDF"):
        if not gt_filename.strip():
            st.warning("Enter a filename first.")
        else:
            try:
                req = DownloadRequest(paper_id=gt_filename.strip())
            except ValidationError as exc:
                st.error(fmt_validation_error(exc))
            else:
                with st.spinner("Fetching GT PDF…"):
                    downloader = PaperDownloader(store=store)
                    result = downloader.download(req)
                if result.success and result.qp_path:
                    st.success(f"Downloaded: `{result.paper_id}`")
                    session = _session_from_filename(gt_filename)
                    parser = GTParser()
                    try:
                        gt_doc = parser.parse(Path(result.qp_path), session=session)
                        st.session_state["gt_doc"] = gt_doc
                        st.session_state["selected_option"] = None
                        st.session_state["dl_results"] = {}
                        st.session_state["scores"] = {}
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Failed to parse GT PDF: {exc}")
                else:
                    st.error(f"Download failed: {result.error}")

# Handle upload
if uploaded is not None and st.session_state["gt_doc"] is None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(uploaded.read())
        tmp_path = Path(tmp.name)
    session = _session_from_filename(uploaded.name)
    parser = GTParser()
    try:
        gt_doc = parser.parse(tmp_path, session=session)
        st.session_state["gt_doc"] = gt_doc
        st.session_state["selected_option"] = None
        st.session_state["dl_results"] = {}
        st.session_state["scores"] = {}
        st.success(
            f"Parsed GT: syllabus `{gt_doc.syllabus_id}`, "
            f"{len(gt_doc.options)} options found."
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to parse GT PDF: {exc}")

gt_doc = st.session_state.get("gt_doc")

if gt_doc is None:
    st.info("Load a GT PDF above to continue.")
    st.stop()

st.success(
    f"✅ GT loaded — Syllabus `{gt_doc.syllabus_id}` · Session `{gt_doc.session}` · "
    f"{len(gt_doc.options)} options: {', '.join(gt_doc.option_codes)}"
)

st.divider()

# ---------------------------------------------------------------------------
# Step 2 — Pick option + bulk download
# ---------------------------------------------------------------------------

st.subheader("Step 2 — Select Option & Bulk Download Papers")

selected_code = st.selectbox(
    "Your option",
    options=gt_doc.option_codes,
    index=(
        gt_doc.option_codes.index(st.session_state["selected_option"])
        if st.session_state["selected_option"] in gt_doc.option_codes
        else 0
    ),
)
st.session_state["selected_option"] = selected_code
option: GradeThreshold = gt_doc.get_option(selected_code)  # type: ignore[assignment]

# Show components for this option
st.markdown(
    f"**Components in {selected_code}:** "
    + " · ".join(f"`{c}`" for c in option.components)
)

# Source selector on top row, session input below
src_col, _ = st.columns([1, 2])
with src_col:
    bulk_source: DownloadSource = st.segmented_control(
        "Source",
        options=["CIEFrank", "PapaCambridge"],
        default="CIEFrank",
        key="bulk_source",
    )  # type: ignore[assignment]

session_input = st.text_input(
    "Session",
    value=gt_doc.session,
    help="e.g. s25, w24, m25",
    max_chars=3,
)

if st.button("⬇️ Bulk Download All Components", type="primary"):
    if not session_input.strip():
        st.warning("Enter a session code first.")
    else:
        dl_results: dict[str, bool] = {}
        downloader = PaperDownloader(store=store)
        progress = st.progress(0, text="Starting downloads…")

        for i, component in enumerate(option.components):
            paper_id = f"{gt_doc.syllabus_id}_{session_input.strip()}_qp_{component}"
            progress.progress(
                (i) / len(option.components),
                text=f"Downloading `{paper_id}`…",
            )
            try:
                req = DownloadRequest(paper_id=paper_id, source=bulk_source)
                result = downloader.download(req)
                dl_results[component] = result.success
                if not result.success:
                    st.warning(f"`{paper_id}`: {result.error}")
            except ValidationError as exc:
                dl_results[component] = False
                st.warning(f"`{paper_id}` invalid: {fmt_validation_error(exc)}")

        progress.progress(1.0, text="Done!")
        st.session_state["dl_results"] = dl_results

        success_count = sum(dl_results.values())
        st.success(f"Downloaded {success_count}/{len(option.components)} papers.")

# Show download status
if st.session_state["dl_results"]:
    cols = st.columns(len(option.components))
    for col, component in zip(cols, option.components, strict=False):
        ok = st.session_state["dl_results"].get(component)
        if ok is True:
            col.success(f"`{component}` ✅")
        elif ok is False:
            col.error(f"`{component}` ❌")
        else:
            col.info(f"`{component}` —")

st.divider()

# ---------------------------------------------------------------------------
# Step 3 — Enter scores + grade comparison
# ---------------------------------------------------------------------------

st.subheader("Step 3 — Enter Scores & See Your Grade")

st.markdown(
    f"**Option {selected_code} thresholds** (max weighted: {option.max_weighted})"
)

# Threshold table
import pandas as pd  # noqa: E402

_all_grades = ["A*", "A", "B", "C", "D", "E"]
threshold_cols = ["Grade"] + [
    g for g in _all_grades if g in option.thresholds
]
threshold_rows = [
    ["Min. mark"] + [str(option.thresholds[g]) for g in threshold_cols[1:]]
]
threshold_df = pd.DataFrame(threshold_rows, columns=threshold_cols)
st.dataframe(threshold_df, width="stretch", hide_index=True)

st.markdown("**Enter your raw scores per component:**")
st.caption("Fill in both your score and the max mark for each component.")

# Per-component: score_raw + score_total inputs
scores_raw: dict[str, float] = {}
scores_total: dict[str, float] = {}

for component in option.components:
    col_label, col_raw, col_sep, col_total = st.columns([2, 2, 0.3, 2])
    col_label.markdown(f"**Component {component}**")

    default_raw = st.session_state["scores"].get(component, {}).get("raw", 0.0)
    default_total = st.session_state["scores"].get(component, {}).get("total", 0.0)

    raw = col_raw.number_input(
        "Score achieved",
        min_value=0.0,
        max_value=9999.0,
        value=default_raw,
        step=0.5,
        key=f"score_raw_{component}",
        label_visibility="collapsed",
    )
    col_sep.markdown(
        "<div style='padding-top:8px;text-align:center'>/</div>",
        unsafe_allow_html=True,
    )
    total = col_total.number_input(
        "Max mark",
        min_value=0.0,
        max_value=9999.0,
        value=default_total,
        step=0.5,
        key=f"score_total_{component}",
        label_visibility="collapsed",
    )
    scores_raw[component] = raw
    scores_total[component] = total

# Persist to session state
st.session_state["scores"] = {
    c: {"raw": scores_raw[c], "total": scores_total[c]}
    for c in option.components
}

total_raw = sum(scores_raw.values())
grade = option.grade_for_score(total_raw)

st.divider()

# Result display
res_col1, res_col2 = st.columns([1, 2])

with res_col1:
    st.metric(
        "Total Raw Score",
        f"{total_raw:.1f}",
        help=f"Max weighted: {option.max_weighted}",
    )
    st.markdown(f"### Grade: {_grade_badge(grade)}", unsafe_allow_html=False)

with res_col2:
    st.markdown("**Where you stand:**")
    for g in ["A*", "A", "B", "C", "D", "E"]:
        if g not in option.thresholds:
            continue
        threshold = option.thresholds[g]
        above = total_raw >= threshold
        marker = " ← you" if g == grade else ""
        st.markdown(f"{'✅' if above else '❌'} **{g}** ({threshold}+){marker}")

st.divider()

# ---------------------------------------------------------------------------
# Save scores to CSV
# ---------------------------------------------------------------------------

st.subheader("💾 Save Scores")
st.caption(
    "Saves each component as a separate record in the tracker. "
    "Only components with a max mark > 0 will be saved."
)

saveable = {
    c for c in option.components
    if scores_total.get(c, 0) > 0
}

if not saveable:
    st.info("Enter at least one max mark above 0 to enable saving.")
else:
    session_for_save = session_input.strip() or gt_doc.session

    # Preview what will be saved
    preview_rows = []
    for component in option.components:
        if component not in saveable:
            continue
        paper_id = f"{gt_doc.syllabus_id}_{session_for_save}_qp_{component}"
        raw = scores_raw[component]
        total = scores_total[component]
        pct = round((raw / total) * 100, 2) if total > 0 else None
        preview_rows.append({
            "Paper ID": paper_id,
            "Score": f"{raw} / {total}",
            "Percentage": f"{pct:.1f}%" if pct is not None else "—",
        })

    preview_df = pd.DataFrame(preview_rows)
    st.dataframe(preview_df, width="stretch", hide_index=True)

    if st.button("💾 Save to Tracker", type="primary"):
        from pydantic import ValidationError as PydanticValidationError

        from modules.manager import PaperManager, ScoreUpdate

        manager = PaperManager(store=store)
        saved, skipped, failed = 0, 0, 0

        for component in option.components:
            if component not in saveable:
                continue

            paper_id = f"{gt_doc.syllabus_id}_{session_for_save}_qp_{component}"
            raw = scores_raw[component]
            total = scores_total[component]

            # Check if record exists in store; if not, we can't submit a score
            all_records = store.load_all()
            exists = any(r.paper_id == paper_id for r in all_records)

            if not exists:
                st.warning(
                    f"`{paper_id}` not found in tracker — "
                    "download it first via Bulk Download."
                )
                skipped += 1
                continue

            try:
                update = ScoreUpdate(
                    paper_id=paper_id,
                    score_raw=raw,
                    score_total=total,
                )
            except PydanticValidationError as exc:
                st.error(f"`{paper_id}`: {fmt_validation_error(exc)}")
                failed += 1
                continue

            score_result = manager.submit_score(update)
            if score_result.success:
                saved += 1
            else:
                st.error(f"`{paper_id}`: {score_result.error}")
                failed += 1

        if saved:
            st.success(f"✅ Saved {saved} record(s) to tracker.")
        if skipped:
            st.warning(f"⚠️ Skipped {skipped} component(s) — not in tracker yet.")
        if failed:
            st.error(f"❌ {failed} component(s) failed to save.")