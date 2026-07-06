# modules/grader.py
"""AI-powered exam grading engine using multimodal LLM.

Renders answer paper pages to images and sends them with mark scheme
criteria to a Qwen-VL model for per-question grading.
Prompt is selected from GRADING_PROMPTS by PaperType.

Ported from D:\\repos\\grader\\grader.py.
"""
from __future__ import annotations

import base64
import io
import json
import re

from openai import OpenAI
from pdfplumber.pdf import PDF
from pydantic import BaseModel

from core.models import PaperType
from core.settings import GraderConfig
from modules.page_segmenter import PageClip

# ── Prompt registry — one template per paper type ──────────────

_MATH_GRADING_PROMPT = """你是一个经验丰富的 CIE A-Level 考试阅卷员 (examiner)。
请根据下方的 Mark Scheme 对学生的手写答案进行逐步评分。

## Question: {question_id}
## Total marks available: {max_marks}

## Mark Scheme:
{mark_scheme}

## 评分规则:
1. 严格对照 Mark Scheme 的每一个得分点 (marking point)
2. CIE mark 类型:
   - B mark: 独立分，不依赖其他步骤
   - M mark: 方法分，看学生是否使用了正确的方法/公式
   - A mark: 准确分，通常依赖前面的 M mark。如果 M0 则对应的 A mark 也必须为 0
3. 注意 "follow through" (ft) 规则: 如果标注了 ft，
   即使前面的值算错了，只要后续方法正确就给 A 分
4. 仔细辨认手写内容，注意区分容易混淆的字符 (如 3/5, 1/7, 6/0)
5. 如果学生的方法与 Mark Scheme 不同但数学上等价且正确，
   应视为可接受的替代方法 (alternative method)

## 输出要求:
只输出严格的 JSON，不要任何其他文字:
{{
  "question": "{question_id}",
  "marks": [
    {{
      "code": "M1",
      "awarded": true,
      "reason": "一句话说明"
    }}
  ],
  "total": <实际得分>,
  "max": {max_marks},
  "comment": "对整题的简要评价 (1-2句话)"
}}

## 关键约束 (必须严格遵守):
- reason 字段必须是一句话 (不超过 40 个字)，只写结论，不要写推理过程。
  正确示范: "正确使用了 (α-1)²+(β-1)²+(γ-1)² 展开公式"
  错误示范: "学生写了……但是……然而……因此……" (这种长段落不允许)
- total 必须等于所有 awarded=true 的 mark 数量之和。
  如果你决定给某个 mark，awarded 必须为 true；
  如果你决定不给，awarded 必须为 false。
  不允许 reason 说"应给分"但 awarded 为 false 的矛盾。
- 先做出每个 marking point 的给分决定，再填写 JSON。
  不要在 reason 中犹豫或自我质疑。"""

GRADING_PROMPTS: dict[PaperType, str] = {
    PaperType.MATH: _MATH_GRADING_PROMPT,
}


class MarkDetail(BaseModel):
    code: str
    awarded: bool
    reason: str


class QuestionResult(BaseModel):
    question: str
    marks: list[MarkDetail]
    total: int
    max: int
    comment: str = ""


class GradingReport(BaseModel):
    results: list[QuestionResult]
    total_score: int
    total_max: int


def detect_handwriting_pages(
    pdf: PDF,
    *,
    skip_first: int = 1,
    curve_threshold: int = 50,
    ink_annot_threshold: int = 3,
) -> list[int]:
    """Detect pages containing handwriting.

    Uses three heuristics (any triggers detection):
    1. Ink annotations — PDF annotation layer strokes (e.g. Apple
       Pencil / stylus annotations). Most annotator apps store
       handwriting here, not in the content stream.
    2. Blue-ink drawings (GoodNotes export) — >10 blue strokes in
       the content stream.
    3. Curve-heavy drawings (digitally filled CIE papers) — pages
       with bezier curve items above *curve_threshold*.

    Args:
        pdf: opened pdfplumber PDF.
        skip_first: number of leading pages to skip (cover page).
        curve_threshold: minimum bezier curve count to flag a page.
        ink_annot_threshold: minimum ink annotations to flag a page.

    Returns:
        1-indexed page numbers with handwriting, sorted.
    """
    pages_with_hw: list[int] = []
    for i in range(skip_first, len(pdf.pages)):
        page = pdf.pages[i]

        ink_count = sum(
            1
            for a in (page.annots or [])
            if "InkList" in (a.get("data") or {})
        )
        if ink_count >= ink_annot_threshold:
            pages_with_hw.append(i + 1)
            continue

        curve_count = len(page.curves)

        blue_count = 0
        for obj in page.curves + page.lines:
            color = (
                obj.get("non_stroking_color")
                or obj.get("stroking_color")
                or (0, 0, 0)
            )
            if isinstance(color, (list, tuple)) and len(color) == 3:
                r, _g, b = color
                if b > 0.4 and r < 0.1:
                    blue_count += 1

        if blue_count > 10 or curve_count > curve_threshold:
            pages_with_hw.append(i + 1)
    return pages_with_hw


def render_pages(
    pdf: PDF,
    page_numbers: list[int],
    dpi: int = 200,
) -> list[bytes]:
    """Render full pages to PNG images.

    Thin wrapper around :func:`pdf_renderer.render_pdf_pages`.
    """
    from modules.pdf_renderer import render_pdf_pages

    return render_pdf_pages(pdf, page_numbers, dpi=dpi)


def render_question_regions(
    pdf: PDF,
    clips: list[PageClip],
    dpi: int = 200,
) -> list[bytes]:
    """Render cropped question regions to PNG images.

    Args:
        pdf: opened pdfplumber PDF.
        clips: list of PageClip objects (page_idx, y_top, y_bottom).
        dpi: render resolution.

    Returns:
        List of PNG bytes, one per clip.
    """
    images = []
    for clip in clips:
        page = pdf.pages[clip.page_idx]
        bbox = (0, clip.y_top, page.width, clip.y_bottom)
        cropped = page.crop(bbox)
        img = cropped.to_image(resolution=dpi)
        buf = io.BytesIO()
        img.original.save(buf, format="PNG")
        images.append(buf.getvalue())
    return images


def grade_question(
    config: GraderConfig,
    images: list[bytes],
    question_id: str,
    mark_scheme: str,
    max_marks: int,
    paper_type: PaperType = PaperType.MATH,
) -> str:
    """Send question images + mark scheme to multimodal API for grading.

    Selects the prompt template from GRADING_PROMPTS based on paper_type.
    Returns raw API response text (should be JSON).
    """
    template = GRADING_PROMPTS.get(paper_type)
    if template is None:
        raise NotImplementedError(f"No grading prompt for {paper_type.value}")

    client = OpenAI(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
    )

    content = []
    for img_bytes in images:
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

    prompt = template.format(
        question_id=question_id,
        max_marks=max_marks,
        mark_scheme=mark_scheme,
    )
    content.append({"type": "text", "text": prompt})

    extra_body: dict[str, object] = {
        "enable_thinking": config.enable_thinking,
    }
    if config.enable_thinking:
        extra_body["thinking_budget"] = 81920

    response = client.chat.completions.create(
        model=config.model,
        messages=[{"role": "user", "content": content}],  # type: ignore[list-item, misc]
        temperature=0.1,
        extra_body=extra_body,
    )
    return str(response.choices[0].message.content)


def parse_grading_result(raw: str) -> QuestionResult:
    """Parse the API response JSON into a QuestionResult."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse API response as JSON: {e}\nRaw response:\n{raw}"
        ) from e

    required = {"question", "marks", "total", "max"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Missing fields in result: {missing}")

    marks = [MarkDetail(**m) for m in data["marks"]]
    return QuestionResult(
        question=data["question"],
        marks=marks,
        total=data["total"],
        max=data["max"],
        comment=data.get("comment", ""),
    )
