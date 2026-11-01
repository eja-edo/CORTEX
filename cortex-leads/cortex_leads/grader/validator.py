"""The checks a suggested grade passes before a teacher sees it (WP33, DESIGN A7 for marks). The model proposes a score per criterion
and the sentence of the student's work it rests on; code decides what survives:
- every criterion of the guide is scored once, none invented, none above its points;
- a criterion that scores anything must quote the student's own words, and the quote must really be in the work: a score resting
  on words that are not there is set to 0 and flagged, never kept (a model that wants to be generous invents evidence);
- the total is the sum of what survived, computed here, never taken from the model;
- a number in the feedback must be one of the scores, the maximum, a number in the teacher's guide or one the student wrote;
- work that talks to the grader ("give me 10 points", "ignore the rubric") is flagged for the teacher.
Nothing here raises: a proposal is always usable, and what was wrong with it is listed for the teacher to read."""
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field

from cortex_leads.grader.guide import Guide

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
ELLIPSIS = re.compile(r"…|\.{3}")
MIN_QUOTE = 4
ADDRESSES_THE_GRADER = re.compile(
    r"(cho|give|tặng)\s+(tôi|em|mình|me)?\s*\d+\s*(điểm|points?|/\s*\d+)|ignore\s+(all|the|previous|your)|bỏ\s+qua\s+(mọi|các|toàn bộ)?\s*(hướng\s*dẫn|quy\s*tắc|tiêu\s*chí|rubric)|"
    r"system\s*prompt|(hãy|please)\s+(chấm|cho điểm|grade)|điểm\s+tối\s+đa", re.IGNORECASE)


class CriterionScore(BaseModel):
    id: str
    score: float = Field(ge=0, le=1000)
    quote: str = Field(default="", max_length=400)
    comment: str = Field(default="", max_length=400)


class Proposal(BaseModel):
    criteria: list[CriterionScore] = Field(min_length=1, max_length=12)
    feedback: str = Field(default="", max_length=800)
    concerns: list[str] = Field(default_factory=list, max_length=5)
    transcript: str = Field(default="", max_length=8000)  # when the work is a photo: the words the model read in it, written out


def norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def quote_is_there(quote: str, content: str) -> bool:
    """Every stretch of the quote (an ellipsis cuts it into stretches) is in the work, ignoring case and spacing."""
    body = norm(content)
    parts = [norm(p).strip(" \"'“”‘’") for p in ELLIPSIS.split(quote)]
    parts = [p for p in parts if p]
    return bool(parts) and sum(len(p) for p in parts) >= MIN_QUOTE and all(p in body for p in parts)


def numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in NUMBER.findall(text)}


def _fmt(x: float) -> str:
    return f"{x:g}"


def check(proposal: Proposal, guide: Guide, content: str) -> dict[str, Any]:
    """{criteria: [{id,label,points,score,proposed,quote,comment,verified}], total, feedback, problems, flags}"""
    by_id = {c.id: c for c in guide.criteria}
    problems: list[str] = []
    seen: dict[str, Any] = {}
    for s in proposal.criteria:
        if s.id not in by_id:
            problems.append(f"Tiêu chí «{s.id}» không có trong thang điểm, đã bỏ qua.")
        elif s.id in seen:
            problems.append(f"Tiêu chí «{s.id}» được chấm hai lần, giữ lần đầu.")
        else:
            seen[s.id] = s
    rows, total = [], 0.0
    for c in guide.criteria:
        s = seen.get(c.id)
        if s is None:
            problems.append(f"Tiêu chí «{c.label}» chưa được chấm, tạm 0 điểm.")
            rows.append({"id": c.id, "label": c.label, "points": c.points, "score": 0.0, "proposed": None, "quote": "", "comment": "",
                         "verified": False})
            continue
        score, verified = min(s.score, c.points), True
        if s.score > c.points:
            problems.append(f"Tiêu chí «{c.label}»: điểm đề xuất {_fmt(s.score)} vượt tối đa {_fmt(c.points)}, đã đưa về mức tối đa.")
        if score > 0 and not quote_is_there(s.quote, content):
            problems.append(f"Tiêu chí «{c.label}»: trích dẫn không có trong bài của học sinh, điểm đề xuất {_fmt(s.score)} đặt lại 0.")
            score, verified = 0.0, False
        score = round(score, 2)
        total += score
        rows.append({"id": c.id, "label": c.label, "points": c.points, "score": score, "proposed": round(s.score, 2),
                     "quote": s.quote.strip(), "comment": s.comment.strip(), "verified": verified})
    total = round(total, 2)
    feedback = proposal.feedback.strip()
    asked = " ".join([guide.title, guide.answer_key or "", *(f"{c.label} {c.descriptor}" for c in guide.criteria)])  # "đủ 5 câu" is the teacher's number
    allowed = (numbers(content) | numbers(asked) | {_fmt(total), _fmt(guide.max_points)} | {_fmt(r["score"]) for r in rows}
               | {_fmt(c.points) for c in guide.criteria})
    if not numbers(feedback) <= {a.replace(",", ".") for a in allowed}:
        problems.append("Lời nhận xét có con số không khớp điểm hoặc bài làm, đã thay bằng bản tóm tắt theo tiêu chí.")
        feedback = " ".join(f"{r['label']}: {_fmt(r['score'])}/{_fmt(r['points'])}." for r in rows)
    flags = ["CONTENT_ADDRESSES_THE_GRADER"] if ADDRESSES_THE_GRADER.search(content) else []
    if flags:
        problems.append("Bài làm có câu nói với người chấm (xin điểm hoặc ra lệnh), hãy đọc kỹ trước khi duyệt.")
    return {"criteria": rows, "total": total, "max_points": guide.max_points, "feedback": feedback,
            "concerns": [c.strip() for c in proposal.concerns if c.strip()], "problems": problems, "flags": flags}


def check_scores(final: dict[str, float], guide: Guide) -> dict[str, float]:
    """The scores a teacher typed: only criteria of the guide, each between 0 and its points. Raises ValueError otherwise."""
    by_id = {c.id: c for c in guide.criteria}
    if set(final) != set(by_id):
        raise ValueError("scores must cover exactly the criteria of the guide")
    for k, v in final.items():
        if not 0 <= v <= by_id[k].points:
            raise ValueError(f"score of {k} must be between 0 and {by_id[k].points}")
    return {k: round(v, 2) for k, v in final.items()}
