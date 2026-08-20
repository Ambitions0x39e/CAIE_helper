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
2. mark 代码 = 类型字母 + 分值数字，例如 B1 / B2 / M1 / A1 / DM1:
   - 字母是类型:
     - B mark: 独立分，不依赖其他步骤
     - M mark: 方法分，看学生是否使用了正确的方法/公式
     - A mark: 准确分，通常依赖前面的 M mark。如果 M0 则对应的 A mark 也必须为 0
     - DM mark: 依赖方法分，它所依赖的那个 M mark 没给分时，DM 也必须为 0
   - **紧跟字母后面的数字是这一个采分点值几分**，不是编号:
     B2 是一个值 2 分的采分点，M1 值 1 分，A1 值 1 分。
     给出 B2 就是给 2 分，不是 1 分。
3. Mark Scheme 行末方括号里的 [Guidance: ...] 是该采分点的评分细则
   (接受/拒绝什么、oe / ft / cao / isw、允许的替代解法)。
   它比你的直觉优先: 细则说可以接受的就必须给分，说要拒绝的就不能给分。
4. 注意 "follow through" (ft) 规则: 如果标注了 ft，
   即使前面的值算错了，只要后续方法正确就给 A 分
5. 仔细辨认手写内容，注意区分容易混淆的字符 (如 3/5, 1/7, 6/0)
6. 如果学生的方法与 Mark Scheme 不同但数学上等价且正确，
   应视为可接受的替代方法 (alternative method)
{topic_block}
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
- total 必须等于所有 awarded=true 的采分点的**分值之和**，
  而不是采分点的个数之和 —— 分值就是 code 里字母后面那个数字。
  例: 给了 B2 和 M1 → total = 2 + 1 = 3 (不是 2)。
  marks 数组里每个采分点占一条，code 原样保留分值数字 (是 B2 就写 B2)。
- total 不得超过 {max_marks}。
- 如果你决定给某个 mark，awarded 必须为 true；
  如果你决定不给，awarded 必须为 false。
  不允许 reason 说"应给分"但 awarded 为 false 的矛盾。
- 先做出每个 marking point 的给分决定，再填写 JSON。
  不要在 reason 中犹豫或自我质疑。"""

GRADING_PROMPTS: dict[PaperType, str] = {
    PaperType.MATH: _MATH_GRADING_PROMPT,
}

# Spliced into ``{topic_block}`` only when the caller knows which topics the
# paper can cover. Without a syllabus the whole section — the list *and* the
# instruction to emit a "topic" field — is absent, rather than present and
# empty: an empty list would invite the model to invent a label.
_TOPIC_BLOCK_TEMPLATE = """
## 该 Paper 覆盖的 Topic 列表:
{topics}

在输出 JSON 里新增一个字段 "topic": 从上面列表里选最贴合这道题内容的 topic_id
(只填 id，例如 "1.2" 或 "7")。如果题目跨多个 topic，选主要考察的那一个；
如果实在无法归入任何一个，"topic" 填 null。
"""


def _render_topic_block(topic_list: dict[str, str] | None) -> str:
    """Render the topic section, or "" when there is nothing to render."""
    if not topic_list:
        return ""
    topics = "\n".join(f"{tid}: {name}" for tid, name in topic_list.items())
    return _TOPIC_BLOCK_TEMPLATE.format(topics=topics)


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
    # Syllabus topic id the model picked for this question. None whenever no
    # syllabus was available, the paper's component isn't in it, or the model
    # could not place the question — all three land in 未分类 downstream.
    topic: str | None = None


class GradingReport(BaseModel):
    results: list[QuestionResult]
    total_score: int
    total_max: int



def grade_question(
    config: GraderConfig,
    images: list[bytes],
    question_id: str,
    mark_scheme: str,
    max_marks: int,
    paper_type: PaperType = PaperType.MATH,
    topic_list: dict[str, str] | None = None,
) -> str:
    """Send question images + mark scheme to multimodal API for grading.

    Selects the prompt template from GRADING_PROMPTS based on paper_type.
    Returns raw API response text (should be JSON).

    ``topic_list`` maps topic_id → name for the topics this paper can cover.
    When it is None or empty the prompt carries no topic section at all and
    the model is never asked for a ``"topic"`` field.
    """
    template = GRADING_PROMPTS.get(paper_type)
    if template is None:
        raise NotImplementedError(f"No grading prompt for {paper_type.value}")

    # Cap the request: the SDK default is 600s × retries (~30 min), which
    # reads as an indefinite hang. Thinking mode legitimately runs longer,
    # so give it a wider budget.
    timeout = 300.0 if config.enable_thinking else 120.0
    client = OpenAI(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
        timeout=timeout,
        max_retries=1,
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
        topic_block=_render_topic_block(topic_list),
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
    topic = data.get("topic")
    return QuestionResult(
        question=data["question"],
        marks=marks,
        total=data["total"],
        max=data["max"],
        comment=data.get("comment", ""),
        # "topic" is optional: prompts built without a topic list never ask
        # for it, and the model may answer null when it cannot place the
        # question. Anything else is coerced to str so a numeric id parses.
        topic=None if topic is None else str(topic),
    )
