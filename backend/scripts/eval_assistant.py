#!/usr/bin/env python3
"""
Eval harness for the Cortex assistant prompt + skills.

Builds the SAME system prompt production uses (system/assistant_system.md +
retriever-selected skills), sends each test case through the LLM API, and
scores the response against the companion-assistant rubric.

Checks whether the agent UNDERSTANDS THE USER'S GOAL instead of just executing
the literal command:
  - goal detected (not just narrated)
  - plan proposed when user states a want
  - proactive supports offered (reminder / checklist / prep block / review)
  - asks with options + concrete defaults, minimal open questions
  - progress reports get updates, not just praise
  - ambiguous statements get confirmation, not blind guesses

Usage:
    python -m scripts.eval_assistant                      # all cases
    python -m scripts.eval_assistant --case ielts         # substring filter
    python -m scripts.eval_assistant --judge              # + LLM judge scores
    python -m scripts.eval_assistant --model <model>      # override model
    python -m scripts.eval_assistant --json               # machine-readable

Scoring is rule-based by default (deterministic, free). Add --judge to have a
second LLM call grade each criterion 1-5.
"""

import argparse
import asyncio
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ai.agents.model_client import ModelClient
from app.ai.agents.provider_types import GenerationConfig, Message, ToolResult
from app.ai.agents.tool_registry import get_tool_registry
from app.ai.loaders.prompt_loader import load
from app.ai.skills import get_skill_retriever, get_skill_registry
from app.config import settings

SYSTEM_PROMPT_PATH = "system/assistant_system.md"


# ---------------------------------------------------------------------------
# Test cases — mirror the companion-assistant spec
# ---------------------------------------------------------------------------

@dataclass
class EvalCase:
    id: str
    message: str
    category: str          # goal | want | event | progress | ambiguous | deadline
    description: str
    expected: dict = field(default_factory=dict)


CASES: list[EvalCase] = [
    EvalCase(
        id="meeting",
        message="Mai tôi họp với khách.",
        category="event",
        description="Event detected → ask time with options + offer supports",
        expected={"options": True, "no_open_question": False},
    ),
    EvalCase(
        id="weightloss",
        message="Tôi muốn giảm 5kg.",
        category="want",
        description="Goal → ask critical facts (timeframe) then propose plan",
        expected={"plan_proposed": True, "options": True, "concrete_defaults": True},
    ),
    EvalCase(
        id="english",
        message="Tôi muốn học tiếng Anh.",
        category="want",
        description="Learning → ask goal type with options, then plan",
        expected={"plan_proposed": True, "options": True, "no_open_question": False},
    ),
    EvalCase(
        id="proposal",
        message="Tuần sau tôi phải nộp proposal.",
        category="deadline",
        description="Deadline → schedule + reminder + prep steps",
        expected={"plan_proposed": True, "proactive_support": True},
    ),
    EvalCase(
        id="travel",
        message="Chủ nhật này tôi đi Đà Nẵng.",
        category="event",
        description="Travel → ask duration/return with options + packing checklist",
        expected={"proactive_support": True, "options": True},
    ),
    EvalCase(
        id="cafe",
        message="Tôi muốn mở quán cafe trong năm nay.",
        category="want",
        description="Multi-skill: research + business plan + finance + schedule",
        expected={"plan_proposed": True, "multi_skill": True},
    ),
    EvalCase(
        id="unit3",
        message="Hôm nay tôi học xong Unit 3.",
        category="progress",
        description="Progress → tick/update, not just praise",
        expected={"update_progress": True, "not_just_praise": True},
    ),
    EvalCase(
        id="cv",
        message="Tôi vừa gửi CV.",
        category="progress",
        description="Complete task → update goal + follow-up reminder",
        expected={"update_progress": True, "proactive_support": True},
    ),
    EvalCase(
        id="finally_done",
        message="Cuối cùng cũng xong.",
        category="ambiguous",
        description="Ambiguous → confirm which task, don't guess",
        expected={"confirmation": True},
    ),
    EvalCase(
        id="react",
        message="Tôi muốn học React.",
        category="want",
        description="Roadmap + prerequisite + project + timeline",
        expected={"plan_proposed": True, "concrete_defaults": True},
    ),
    EvalCase(
        id="doctor",
        message="Mai tôi đi khám bệnh.",
        category="event",
        description="Doctor → ask time with options, offer reminders/documents",
        expected={"options": True, "no_open_question": False},
    ),
    EvalCase(
        id="run5km",
        message="Tôi chạy được 5km.",
        category="progress",
        description="Workout → update progress/goal/streak",
        expected={"update_progress": True, "not_just_praise": True},
    ),
]


# ---------------------------------------------------------------------------
# Rule-based rubric
# ---------------------------------------------------------------------------

_RULE_BANK: dict[str, tuple[str, str]] = {
    "plan_proposed": (
        "response proposes a structured plan (phases/milestones/schedule/checklist)",
        r"\b(plan|kế hoạch|lộ trình|roadmap|phase|giai đoạn|bước|milestone|cột mốc)\b",
    ),
    "proactive_support": (
        "offers reminder/checklist/prep block/review beyond the literal ask",
        r"\b(reminder|nhắc nhở|checklist|danh sách|chuẩn bị|review|theo dõi|follow-up|track)\b",
    ),
    "options": (
        "asks with concrete options rather than open questions",
        r"([○●•▪◦]|\b\d+[.)]\s|^[-*]\s|\bhay\s+[^\n]{2,60}?\?|\bhoặc\s|\bor\s+[^\n]{2,60}?\?|\b\d{2}:\d{2}\b|\b\d+\s*phút\b|\bsáng\b|\bchiều\b|\btối\b|\blựa chọn\b|option\s*\d)",
    ),
    "concrete_defaults": (
        "proposes concrete default values (duration, frequency, time)",
        r"(\d+\s*(phút|ngày|tuần|tháng|km|kg|lần)|09:00|19:00|30 phút|5 ngày/tuần)",
    ),
    "confirmation": (
        "asks for confirmation / approval (Áp dụng luôn? / Điều chỉnh? / Đúng không?)",
        r"(áp dụng luôn|điều chỉnh|đúng không|như mọi khi|ok\??|okay\?|confirm|approve|được không|nghĩ sao|phải không|đề cập đến|nào vậy|đang nói về|việc gì\?|điều gì\?)",
    ),
    "no_open_question": (
        "does NOT ask generic open questions (thế nào / bao nhiêu / khi nào / gì ?)",
        r"(muốn (học|làm|tập) thế nào|học lúc nào|tập bao lâu|bao nhiêu lâu|học bao lâu)",
    ),
    "update_progress": (
        "acknowledges and updates progress toward the goal (not just praise)",
        r"(xong|tick|đánh dấu|cập nhật|update|progress|tiến độ|hoàn thành|đã (xong|gửi|nộp|thanh toán)|thêm|đạt)",
    ),
    "not_just_praise": (
        "adds value beyond congratulation (next step / follow-up / what's next)",
        r"(bước tiếp|tiếp theo|next|follow-up|giờ thì|nhớ|còn lại|đề xuất|sắp tới|cập nhật tiến độ|tạo mục tiêu|theo dõi sau)",
    ),
    "multi_skill": (
        "addresses multiple dimensions of a rich statement",
        r"(vốn|ngân sách|budget|địa điểm|location|nhân sự|marketing|pháp lý|giấy phép|giá|chi phí|doanh thu)",
    ),
    "goal_detected": (
        "recognizes the underlying goal/intent of the message",
        r"(muốn|mục tiêu|goal|hướng tới|đạt|hoàn thành|kế hoạch)",
    ),
}


def _rule_hits(text: str, regex: str) -> int:
    return len(re.findall(regex, text, flags=re.IGNORECASE))


def score_rules(message: str, response: str, expected: dict) -> dict:
    """Return per-criterion pass/fail plus hit counts."""
    text = f"{response}\n{message}" if response else message
    results: dict[str, dict] = {}
    for criterion in _RULE_BANK:
        _, regex = _RULE_BANK[criterion]
        hits = _rule_hits(text, regex)
        want = expected.get(criterion, False)
        # Pass when a criterion is expected and hit, or not expected and not hit.
        passed = hits > 0 if want else (hits == 0 if criterion in expected else None)
        results[criterion] = {"expected": want, "hits": hits, "passed": passed}
    return results


# ---------------------------------------------------------------------------
# LLM judge (optional)
# ---------------------------------------------------------------------------

JUDGE_SYSTEM = """You are a strict evaluator of an AI productivity assistant's responses.
Score each criterion 1-5 based ONLY on the assistant's response to the user message.
5 = strongly meets, 3 = partially meets, 1 = clearly fails.

Criteria to judge:
- goal_understanding: understands the user's real goal/intent, not just the literal words
- plan_proposed: when the user states a want/goal, proposes a concrete structured plan
- proactive_support: offers reminder/checklist/prep/review/tracking beyond the literal ask
- options_and_defaults: asks with concrete options and defaults instead of open questions
- minimal_friction: asks few questions; defers non-blocking details
- progress_updates: progress reports get an update/next-step, not just praise
- one_step_ahead: thinks ahead (follow-up, risks, next actions)

Reply with JSON only: {"criterion": score, ...} with no prose."""


def _format_judge_prompt(case: EvalCase, response: str) -> str:
    return (
        f"User message: {case.message!r}\n"
        f"Category: {case.category} ({case.description})\n"
        f"---\nAssistant response:\n{response}\n---\n"
        "Score each criterion 1-5 as JSON."
    )


# ---------------------------------------------------------------------------
# System prompt construction (mirrors conversation_service.build_system_prompt)
# ---------------------------------------------------------------------------

def build_eval_system_prompt(message: str) -> str:
    system_prompt = load(SYSTEM_PROMPT_PATH)
    retriever = get_skill_retriever()
    registry = get_skill_registry()
    selected = retriever.select(message, max_skills=3)
    if not selected:
        return system_prompt
    skills = registry.load_all([s.name for s in selected])
    blocks = [
        f"=== SKILL: {skill.metadata.name.upper()} ===\n{skill.prompt}"
        for skill in skills
    ]
    return system_prompt + "\n\n" + "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

MAX_TOOL_TURNS = 2


async def run_case(client: ModelClient, case: EvalCase, use_judge: bool, model: str | None) -> dict:
    system_prompt = build_eval_system_prompt(case.message)
    messages = [Message(role="user", content=case.message, created_at=datetime.now(timezone.utc))]
    config = GenerationConfig(system_instruction=system_prompt, temperature=0.4, max_output_tokens=800)
    tools = get_tool_registry().get_provider_tools()

    try:
        # Simulate the production tool loop: the model may call tools, we return
        # an empty-result mock, then it produces the final text to score.
        model_used = model or settings.OPENAI_DEFAULT_MODEL
        for turn in range(MAX_TOOL_TURNS + 1):
            model_used, response = await client.generate(messages, config, tools=tools, estimated_tokens=2500)
            if not response.tool_calls:
                break
            assistant_msg = Message(role="assistant", tool_calls=response.tool_calls, created_at=datetime.now(timezone.utc))
            messages.append(assistant_msg)
            for tc in response.tool_calls:
                mock = {"result": {"items": [], "message": "no data found (eval mock)"}, "success": True}
                messages.append(
                    Message(
                        role="tool",
                        tool_result=ToolResult(tool_call_id=tc.id, name=tc.name, content=mock),
                        created_at=datetime.now(timezone.utc),
                    )
                )
        content = response.content or ""
        if not content:
            # Weak models occasionally emit an empty completion; retry once so
            # flakiness is not scored as a prompt failure.
            _, retry = await client.generate(messages, config, tools=tools, estimated_tokens=2500)
            content = retry.content or ""
            model_used = model_used
    except Exception as exc:
        return {
            "id": case.id, "category": case.category, "message": case.message,
            "error": str(exc)[:300], "model": model or settings.OPENAI_DEFAULT_MODEL,
            "response": "", "rules": {}, "judge": None,
        }

    rules = score_rules(case.message, content, case.expected)

    judge = None
    if use_judge and content:
        try:
            judge_msgs = [
                Message(role="user", content=_format_judge_prompt(case, content), created_at=datetime.now(timezone.utc))
            ]
            judge_config = GenerationConfig(system_instruction=JUDGE_SYSTEM, temperature=0, max_output_tokens=400)
            _, jr = await client.generate(judge_msgs, judge_config, estimated_tokens=1500)
            judge_raw = (jr.content or "").strip()
            judge = _parse_judge(judge_raw)
        except Exception as exc:
            judge = {"error": str(exc)[:200]}

    return {
        "id": case.id, "category": case.category, "message": case.message,
        "model": model_used, "response": content, "rules": rules, "judge": judge,
    }


def _parse_judge(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {"raw": raw[:300]}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"raw": raw[:300]}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _rule_summary(result: dict) -> int:
    rules = result.get("rules") or {}
    passed = sum(1 for r in rules.values() if r.get("passed") is True)
    total = sum(1 for r in rules.values() if r.get("passed") is not None)
    return passed, total


def print_report(results: list[dict], use_judge: bool) -> None:
    print("\n" + "=" * 80)
    print("CORTEX ASSISTANT — RESPONSE QUALITY EVAL")
    print("=" * 80)

    total_rule_pass = 0
    total_rule_check = 0
    judge_scores: list[dict] = []

    for r in results:
        if r.get("error"):
            print(f"\n[{r['id']}] ERROR — {r['error']}")
            continue
        p, t = _rule_summary(r)
        total_rule_pass += p
        total_rule_check += t
        print(f"\n[{r['id']}] {r['category']} — {r['message']}")
        print(f"    model: {r['model']}")
        print(f"    rule score: {p}/{t}")

        failed = [k for k, v in r["rules"].items() if v.get("passed") is False]
        if failed:
            print(f"    ✗ expected but missing: {', '.join(failed)}")

        if use_judge and r.get("judge"):
            judge_scores.append(r["judge"])
            scores = {k: v for k, v in r["judge"].items() if isinstance(v, (int, float))}
            if scores:
                avg = sum(scores.values()) / len(scores)
                print(f"    judge avg: {avg:.1f}/5  {scores}")

        resp = r.get("response") or ""
        print(f"    response ({len(resp)} chars): {resp[:400]!r}{'…' if len(resp) > 400 else ''}")

    print("\n" + "-" * 80)
    print(f"RULE SUMMARY: {total_rule_pass}/{total_rule_check} criteria met")

    if judge_scores:
        all_scores: list[float] = []
        for js in judge_scores:
            all_scores += [v for v in js.values() if isinstance(v, (int, float))]
        if all_scores:
            print(f"JUDGE SUMMARY: avg {sum(all_scores) / len(all_scores):.1f}/5 over {len(all_scores)} scores")
    print("-" * 80)


async def main_async(args) -> None:
    cases = [c for c in CASES if not args.case or args.case.lower() in c.id.lower()]
    if not cases:
        print(f"No cases matched --case {args.case!r}")
        sys.exit(1)

    client = ModelClient(models=[args.model] if args.model else None)

    results = []
    for i, case in enumerate(cases, 1):
        print(f"→ running {case.id} ({i}/{len(cases)})…")
        result = await run_case(client, case, args.judge, args.model)
        results.append(result)

    print_report(results, args.judge)

    if args.json:
        print("\nJSON:\n" + json.dumps(results, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval Cortex assistant prompt+skills via LLM API")
    parser.add_argument("--case", help="Run only cases whose id contains this substring")
    parser.add_argument("--judge", action="store_true", help="Add LLM judge scores (extra API call per case)")
    parser.add_argument("--model", help="Override LLM model (default: settings.OPENAI_DEFAULT_MODEL)")
    parser.add_argument("--json", action="store_true", help="Also dump full results as JSON")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
