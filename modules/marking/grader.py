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

from core.models import ERROR_TYPES, ErrorType, PaperType
from core.settings import GraderConfig

# ── Prompt registry — one template per paper type ──────────────

_GRADING_PROMPT = """你是一个经验丰富的 CIE A-Level 考试阅卷员 (examiner)。
请根据下方的 Mark Scheme 对学生的手写答案进行逐步评分。

## Question: {question_id}
## Total marks available: {max_marks}

## Mark Scheme:
{mark_scheme}

## 评分规则:
{rules}{topic_block}
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
  "max": {max_marks},
  "comment": "对整题的简要评价 (1-2句话)",
  "error_type": "<丢分原因，见下方；满分填 null>"
}}

## 丢分原因 (error_type):
没拿满分时，从下面选**一个**最主要的原因填进 "error_type"；拿满分填 null。
- concept: 概念没掌握 —— 定义、原理本身理解错
- method: 路子错 —— 懂概念，但选错了方法、公式或解题路线
- slip: 失误 —— 思路对，算错、抄错、漏项、单位或有效数字错
- misread: 审题 —— 漏看条件、答非所问
- wording: 表述 —— 意思对，但没用 Mark Scheme 要求的说法或关键词
- blank: 没作答，或没做完

## 关键约束 (必须严格遵守):
- reason 字段必须是一句话 (不超过 40 个字)，只写结论，不要写推理过程。
  正确示范: "正确使用了 (α-1)²+(β-1)²+(γ-1)² 展开公式"
  错误示范: "学生写了……但是……然而……因此……" (这种长段落不允许)
- **不要在任何字段里写 LaTeX 或反斜杠**。要写数学符号就直接用 Unicode
  (Σ、√、≤、α、²)，不要写 $\\Sigma$、\\frac{{a}}{{b}} 这类命令 ——
  反斜杠不是合法的 JSON 转义，整个回复会因此解析失败。
- Mark Scheme 的每个采分点在 marks 数组里各占一条，一个都不能漏：没给分的也要列出，
  awarded 填 false。code 原样保留分值数字 (是 B2 就写 B2)，
  得分按 awarded=true 的 code 分值加总。
- 如果你决定给某个 mark，awarded 必须为 true；
  如果你决定不给，awarded 必须为 false。
  不允许 reason 说"应给分"但 awarded 为 false 的矛盾。
- 先做出每个 marking point 的给分决定，再填写 JSON。
  不要在 reason 中犹豫或自我质疑。"""

_MATH_RULES = """1. 严格对照 Mark Scheme 的每一个得分点 (marking point)
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
"""

# From 9702's own "Science-Specific Marking Principles" pages.
_PHYSICS_RULES = """1. 严格对照 Mark Scheme 的每一个得分点 (marking point)
2. mark 代码 = 类型字母 + 分值数字，例如 B1 / C1 / M1 / A1:
   - 字母是类型:
     - B mark: 独立分，不依赖其他步骤
     - C mark: 计算题的补偿分。学生没把这一步写出来，但后面正确的推导或正确的
       最终答案说明他一定用到了它，C mark 照样给分
     - M mark: 方法分，看学生是否使用了正确的方法/公式
     - A mark: 准确分，通常是最终答案
   - **紧跟字母后面的数字是这一个采分点值几分**，不是编号:
     B2 是一个值 2 分的采分点，C1 值 1 分，A1 值 1 分。
     给出 B2 就是给 2 分，不是 1 分。
   - 括号里的 code，如 (C1)、(A1)，属于 "OR" 后面的另一条解法，不是额外的分:
     只按学生实际采用的那条路线给分，两条路线的分不能相加。
3. Mark Scheme 行末方括号里的 [Guidance: ...] 是该采分点的评分细则。
   它比你的直觉优先: 细则说可以接受的就必须给分，说要拒绝的就不能给分。
4. 计算题:
   - 最终答案正确，即使没有过程或过程有误也给满分，除非题目要求 "show your working"
   - 没有单独的单位分时，最终答案缺单位或单位错误，最后那个计算分不给
   - 题目没规定有效数字时，学生答案按 Mark Scheme 答案的有效数字取舍后一致就给分
   - 标准形式 a × 10ⁿ 的系数不在 1 到 10 之间也可以，只要能换算成 Mark Scheme 的答案
5. error carried forward (ecf): 前面算错的值被科学上正确地代入后面，后面的得分点照样给
6. 文字题:
   - 关键词必须用得科学正确才给分，光出现关键词不够
   - 同一小问里互相矛盾的说法，正确的那句也不给分；与题目无关的错误物理忽略
   - 要求 n 个答案的题 (如 "State two reasons"): 当成连续文字读，错误答案也占 n 个名额，
     与其他答案矛盾的答案不给分，第 n 个之后不矛盾的内容忽略
7. 仔细辨认手写内容，注意区分容易混淆的字符 (如 3/5, 1/7, 6/0)、10 的幂和单位前缀
"""

GRADING_PROMPTS: dict[PaperType, str] = {
    PaperType.MATH: _GRADING_PROMPT.replace("{rules}", _MATH_RULES),
    PaperType.PHYSICS: _GRADING_PROMPT.replace("{rules}", _PHYSICS_RULES),
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
    #: Summed from ``marks`` by ``parse_grading_result``, never the model's
    #: own figure: asked for both, it listed five points and reported six.
    total: int
    max: int
    comment: str = ""
    # Syllabus topic id the model picked for this question. None whenever no
    # syllabus was available, the paper's component isn't in it, or the model
    # could not place the question — all three land in 未分类 downstream.
    topic: str | None = None
    error_type: ErrorType | None = None
    #: Filled by ``grade_sheet``: the model's reply carries no paper id.
    paper_id: str = ""


def mark_value(code: str) -> int:
    """What one marking point is worth: the digits closing its code.

    ``B2`` → 2, ``M1`` → 1, ``DM1`` → 1. A code without them counts 1.
    """
    m = _MARK_VALUE_RE.search(code)
    return int(m.group(1)) if m else 1


_MARK_VALUE_RE = re.compile(r"(\d+)\s*$")


def listed_marks(result: QuestionResult) -> int:
    """The marks the reply accounts for, awarded or not. Short of ``max``
    means a marking point was left out of ``marks`` altogether."""
    return sum(mark_value(m.code) for m in result.marks)


def grade_question(
    config: GraderConfig,
    images: list[bytes],
    question_id: str,
    mark_scheme: str,
    max_marks: int,
    paper_type: PaperType = PaperType.MATH,
    topic_list: dict[str, str] | None = None,
    missing_marks: int | None = None,
) -> str:
    """Send question images + mark scheme to multimodal API for grading.

    Selects the prompt template from GRADING_PROMPTS based on paper_type.
    Returns raw API response text (should be JSON).

    ``topic_list`` maps topic_id → name for the topics this paper can cover.
    When it is None or empty the prompt carries no topic section at all and
    the model is never asked for a ``"topic"`` field.

    ``missing_marks`` re-asks after a reply whose ``marks`` fell short of
    ``max_marks`` by that many, naming the gap.
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
    if missing_marks:
        prompt += (
            f"\n\n上一次的 marks 数组漏了采分点：列出的分值合计比满分 {max_marks} "
            f"少 {missing_marks} 分。逐条对照 Mark Scheme，把漏掉的采分点补进 marks。"
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


#: Matches a *valid* JSON escape first, so an already-correct ``\\`` is
#: consumed as one unit and left alone; a lone backslash falls through to the
#: second branch. Scanning for lone backslashes without that first branch
#: would turn a correct ``\\`` into ``\\\``, corrupting good responses while
#: fixing bad ones.
_JSON_ESCAPE_RE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})|\\')


def _escape_stray_backslashes(text: str) -> str:
    """Escape backslashes that JSON would reject, leaving valid ones intact."""
    return _JSON_ESCAPE_RE.sub(
        lambda m: m.group(0) if m.group(1) else "\\\\", text
    )


def parse_grading_result(raw: str) -> QuestionResult:
    """Parse the API response JSON into a QuestionResult."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Second chance for the one malformation the model reliably produces:
        # LaTeX inside `reason` ("$\Sigma y^2 = (\Sigma y)^2$"). ``\S`` is not
        # a JSON escape, so the whole response is rejected and a question that
        # was graded correctly is reported as a failure. Repairing beats
        # discarding — the alternative costs another paid API round trip.
        try:
            data = json.loads(_escape_stray_backslashes(cleaned))
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Failed to parse API response as JSON: {e}\n"
                f"Raw response:\n{raw}"
            ) from e

    required = {"question", "marks", "max"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Missing fields in result: {missing}")

    marks = [MarkDetail(**m) for m in data["marks"]]
    awarded = sum(mark_value(m.code) for m in marks if m.awarded)
    topic = data.get("topic")
    error_type = data.get("error_type")
    return QuestionResult(
        question=data["question"],
        marks=marks,
        total=min(awarded, data["max"]),
        max=data["max"],
        comment=data.get("comment", ""),
        # "topic" is optional: prompts built without a topic list never ask
        # for it, and the model may answer null when it cannot place the
        # question. Anything else is coerced to str so a numeric id parses.
        topic=None if topic is None else str(topic),
        # A value outside the list is the model improvising a category;
        # unclassified is more honest than a guess at which one it meant.
        error_type=error_type if error_type in ERROR_TYPES else None,
    )
