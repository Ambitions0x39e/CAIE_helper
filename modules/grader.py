# modules/grader.py
"""AI-powered exam grading engine using multimodal LLM.

Renders answer paper pages to images and sends them with mark scheme
criteria to a Qwen-VL model for per-question grading.
Prompt is selected from GRADING_PROMPTS by PaperType.

Ported from D:\\repos\\grader\\grader.py.
"""
from __future__ import annotations

import base64
import json
import re

import fitz
from openai import OpenAI
from pydantic import BaseModel

from core.models import PaperType
from core.settings import GraderConfig

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
3. 注意 "follow through" (ft) 规则: 如果标注了 ft，即使前面的值算错了，
   只要后续方法正确就给 A 分
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
      "reason": "简要说明为什么给分/扣分"
    }}
  ],
  "total": <实际得分>,
  "max": {max_marks},
  "comment": "对整题的简要评价 (1-2句话)"
}}"""

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
    doc: fitz.Document,
    *,
    skip_first: int = 1,
    curve_threshold: int = 50,
) -> list[int]:
    """Detect pages containing handwriting.

    Uses two heuristics (either triggers detection):
    1. Blue-ink drawings (GoodNotes export) — >10 blue strokes.
    2. Curve-heavy drawings (digitally filled CIE papers) — pages
       with bezier curve items above *curve_threshold*. Blank answer
       pages have 0 curves; printed-only question text uses the font
       layer, not drawing curves.

    Args:
        doc: opened PyMuPDF document.
        skip_first: number of leading pages to skip (cover page).
        curve_threshold: minimum bezier curve count to flag a page.

    Returns:
        1-indexed page numbers with handwriting, sorted.
    """
    pages_with_hw: list[int] = []
    for i in range(skip_first, len(doc)):
        page = doc[i]
        drawings = page.get_drawings()

        blue_count = 0
        curve_count = 0
        for d in drawings:
            for item in d.get("items", []):
                if item[0] == "c":
                    curve_count += 1
            color = d.get("fill") or d.get("color") or (0, 0, 0)
            if len(color) == 3:
                r, _g, b = color
                if b > 0.4 and r < 0.1:
                    blue_count += 1

        if blue_count > 10 or curve_count > curve_threshold:
            pages_with_hw.append(i + 1)
    return pages_with_hw


def render_pages(
    doc: fitz.Document,
    page_numbers: list[int],
    dpi: int = 200,
) -> list[bytes]:
    """Render full pages to PNG images.

    Thin wrapper around :func:`pdf_renderer.render_pdf_pages`.
    """
    from modules.pdf_renderer import render_pdf_pages

    return render_pdf_pages(doc, page_numbers, dpi=dpi)


def render_question_regions(
    doc: fitz.Document,
    clips: list,
    dpi: int = 200,
) -> list[bytes]:
    """Render cropped question regions to PNG images.

    Args:
        doc: opened PyMuPDF document.
        clips: list of PageClip objects (page_idx, y_top, y_bottom).
        dpi: render resolution.

    Returns:
        List of PNG bytes, one per clip.
    """
    images = []
    for clip in clips:
        page = doc[clip.page_idx]
        rect = fitz.Rect(0, clip.y_top, page.rect.width, clip.y_bottom)
        pix = page.get_pixmap(dpi=dpi, clip=rect)
        images.append(pix.tobytes("png"))
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
        messages=[{"role": "user", "content": content}],  # type: ignore[list-item]
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
