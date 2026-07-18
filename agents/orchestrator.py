# agents/orchestrator.py
"""
BẢN VÁ: thêm 2 tham số use_rag và use_risk_check vào run_orchestrator(), cho
phép Frontend bật/tắt RAG và Risk Warning THẬT theo từng request (không dùng
biến global, an toàn khi nhiều người demo cùng lúc).

Thay thế toàn bộ nội dung file agents/orchestrator.py hiện tại bằng file này.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import time as time_module
from typing import Any

from prompts.system_prompts import ORCHESTRATOR_PROMPT, SYSTEM_PROMPTS
from tools.banking_tools import (
    calculate_loan_eligibility,
    check_credit_score,
    create_approval_ticket,
    query_customer_profile,
    query_policy,
)
from tools.fpt_inference import call_fpt_model
from tools.memory import CaseMemory


# Case Memory toàn cục — một phiên làm việc.
CASE_MEMORY = CaseMemory()

# Log lần chạy gần nhất — main.py / api.py dùng cho Agent Trace Dashboard.
LAST_RUN_LOG: dict[str, Any] = {
    "user_input": "",
    "experts_called": [],
    "task_plan": {},
    "tool_calls": [],
    "synthesis_used": False,
    "timings": {},
    "risk_flagged": False,
    "memory_state": {},
    "settings_used": {"use_rag": True, "use_risk_check": True},
}

EXPERT_PROMPTS = SYSTEM_PROMPTS

ROUTING_KEYWORDS = {
    "credit": [
        "vay",
        "tín dụng",
        "hồ sơ vay",
        "trả nợ",
        "cic",
        "điểm tín dụng",
        "dti",
        "ltv",
        "hạn mức",
        "nợ xấu",
    ],
    "legal": [
        "kyc",
        "aml",
        "tuân thủ",
        "quy định",
        "pháp lý",
        "rửa tiền",
        "nhnn",
        "báo cáo giao dịch",
    ],
    "product": [
        "sản phẩm",
        "lãi suất",
        "thẻ",
        "tiết kiệm",
        "bảo hiểm",
        "gói vay",
        "ưu đãi",
    ],
    "operations": [
        "quy trình",
        "phê duyệt",
        "thủ tục",
        "sla",
        "thời gian xử lý",
        "luồng duyệt",
    ],
}

RISK_KEYWORDS = [
    "nợ xấu",
    "vượt hạn mức",
    "rửa tiền",
    "vi phạm quy định",
    "từ chối hồ sơ",
    "khách hàng lớn",
    "ngoại lệ chính sách",
    "giao dịch lớn",
    "dti cao",
    "bất thường",
]

RISK_WARNING = (
    "⚠️ CẢNH BÁO RỦI RO: Yêu cầu này liên quan đến quyết định có rủi ro cao "
    "hoặc cần tuân thủ nghiêm ngặt, cần cán bộ có thẩm quyền xem xét kỹ trước "
    "khi phê duyệt.\n\n"
)

# query_policy được cấp cho CẢ 4 Expert để mỗi Expert dùng đúng KB riêng.
EXPERT_TOOLS = {
    "credit": [
        "query_policy",
        "check_credit_score",
        "query_customer_profile",
        "calculate_loan_eligibility",
    ],
    "legal": ["query_policy"],
    "product": ["query_policy"],
    "operations": ["query_policy", "create_approval_ticket"],
}

TOOL_FUNCTIONS = {
    "check_credit_score": check_credit_score,
    "query_customer_profile": query_customer_profile,
    "calculate_loan_eligibility": calculate_loan_eligibility,
    "query_policy": query_policy,
    "create_approval_ticket": create_approval_ticket,
}

EXPERT_DISPLAY_NAMES = {
    "credit": "Credit Expert",
    "legal": "Legal & Compliance Expert",
    "product": "Product Expert",
    "operations": "Operations Expert",
}


def decide_experts_fast(user_input: str) -> list[str]:
    """Chọn Expert bằng keyword routing nhanh, không tốn thêm một lần gọi model."""
    lowered = user_input.lower()
    matched = [
        expert
        for expert, keywords in ROUTING_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]
    return matched if matched else list(EXPERT_PROMPTS.keys())


def _extract_json_object(response: str) -> dict[str, Any]:
    """Parse JSON object từ phản hồi có thể bị bọc trong markdown code fence."""
    if not response:
        return {}

    cleaned = response.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}

    try:
        parsed = json.loads(cleaned[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def planner_decompose(user_input: str, experts_to_call: list[str]) -> dict[str, str]:
    """
    Planner chia yêu cầu thành sub-task riêng cho từng Expert.

    Nếu model trả JSON lỗi hoặc bị cắt, hệ thống fallback về câu hỏi gốc để demo
    không bị crash.
    """
    if len(experts_to_call) <= 1:
        return {expert: user_input for expert in experts_to_call}

    expert_names_str = ", ".join(experts_to_call)
    planner_prompt = f"""
Bạn là Planner Agent. Yêu cầu của cán bộ:
{user_input}

Các Expert sẽ tham gia: {expert_names_str}

Với MỖI Expert, hãy viết một nhiệm vụ riêng, đúng chuyên môn và vẫn giữ đầy đủ
các số liệu quan trọng từ yêu cầu gốc.

Trả lời DUY NHẤT bằng một JSON object hợp lệ, không dùng markdown, không giải thích.
Ví dụ:
{{"credit": "...", "legal": "...", "product": "...", "operations": "..."}}
Chỉ liệt kê đúng các Expert sau: {expert_names_str}
"""

    try:
        response = call_fpt_model(
            system_prompt="Bạn chỉ trả JSON object hợp lệ, không giải thích.",
            user_message=planner_prompt,
            max_tokens=800,
        )
        plan = _extract_json_object(response)
    except Exception:
        plan = {}

    result: dict[str, str] = {}
    for expert in experts_to_call:
        sub_task = plan.get(expert)
        result[expert] = (
            sub_task.strip()
            if isinstance(sub_task, str) and sub_task.strip()
            else user_input
        )
    return result


def extract_customer_id(text: str) -> str:
    """Tìm mã khách hàng dạng KH001, KH002...; fallback KH001 để demo."""
    match = re.search(r"\bKH\d{3,}\b", text.upper())
    return match.group(0) if match else "KH001"


def _extract_explicit_customer_id(text: str) -> str | None:
    """Chỉ trả mã khách hàng khi người dùng thực sự nhập mã trong yêu cầu."""
    match = re.search(r"\bKH\d{3,}\b", text.upper())
    return match.group(0) if match else None


def _extract_million_amount(text: str, labels: list[str]) -> float | None:
    """Lấy số tiền dạng '70 triệu' sau một trong các nhãn cho trước."""
    for label in labels:
        pattern = rf"{label}\s*(?:là|:|=)?\s*(\d+(?:[.,]\d+)?)\s*triệu"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", ".")) * 1_000_000
    return None


def _deduplicate_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Loại tool call trùng nhau để tránh gọi và cache nhiều lần."""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []

    for call in tool_calls:
        key = json.dumps(call, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            result.append(call)
    return result


def decide_tool_calls(
    expert_name: str,
    user_input: str,
    use_rag: bool = True,
) -> list[dict[str, Any]]:
    """
    Quyết định tool theo luật ổn định.

    use_rag=False: bỏ qua hoàn toàn tool query_policy (tắt RAG), Expert sẽ trả
    lời chỉ dựa trên kiến thức tổng quát của model, không có trích dẫn nguồn.
    """
    available_tools = EXPERT_TOOLS.get(expert_name, [])
    if not available_tools:
        return []

    tool_calls: list[dict[str, Any]] = []

    # RAG chỉ được gọi khi use_rag=True.
    if use_rag and "query_policy" in available_tools:
        tool_calls.append(
            {
                "tool": "query_policy",
                "args": {
                    "topic": user_input.strip(),
                    "expert_name": expert_name,
                    "top_k": 3,
                },
            }
        )

    lowered = user_input.lower()
    explicit_customer_id = _extract_explicit_customer_id(user_input)

    # Chỉ gọi dữ liệu khách hàng mock khi có mã KH rõ ràng, tránh KH001 fallback
    # làm ghi đè các dữ kiện người dùng vừa cung cấp.
    if expert_name == "credit" and explicit_customer_id:
        if "check_credit_score" in available_tools and any(
            keyword in lowered
            for keyword in ["cic", "điểm tín dụng", "nợ xấu", "lịch sử tín dụng"]
        ):
            tool_calls.append(
                {
                    "tool": "check_credit_score",
                    "args": {"customer_id": explicit_customer_id},
                }
            )

        if "query_customer_profile" in available_tools and any(
            keyword in lowered
            for keyword in ["thu nhập", "dư nợ", "hồ sơ khách hàng", "nợ hiện tại"]
        ):
            tool_calls.append(
                {
                    "tool": "query_customer_profile",
                    "args": {"customer_id": explicit_customer_id},
                }
            )

    # Chỉ tính DTI bằng tool khi người dùng đã cung cấp đủ cả ba đầu vào.
    if expert_name == "credit" and "calculate_loan_eligibility" in available_tools:
        income = _extract_million_amount(user_input, [r"thu nhập(?:/tháng)?"])
        existing_debt = _extract_million_amount(
            user_input,
            [
                r"nghĩa vụ trả nợ hiện tại",
                r"nợ hiện tại",
                r"dư nợ hàng tháng",
            ],
        )
        new_payment = _extract_million_amount(
            user_input,
            [
                r"khoản trả nợ mới",
                r"trả khoản vay mới",
                r"tiền trả hàng tháng dự kiến",
            ],
        )

        if income is not None and existing_debt is not None and new_payment is not None:
            tool_calls.append(
                {
                    "tool": "calculate_loan_eligibility",
                    "args": {
                        "income": income,
                        "existing_debt_monthly": existing_debt,
                        "new_loan_monthly_payment": new_payment,
                    },
                }
            )

    # Tool hành động chỉ chạy khi người dùng yêu cầu rõ ràng.
    if expert_name == "operations" and "create_approval_ticket" in available_tools:
        wants_ticket = any(
            phrase in lowered
            for phrase in ["tạo phiếu", "lập phiếu", "tạo ticket", "trình phiếu"]
        )
        if wants_ticket:
            tool_calls.append(
                {
                    "tool": "create_approval_ticket",
                    "args": {
                        "customer_id": explicit_customer_id or "KH001",
                        "decision": "Chờ thẩm định và phê duyệt",
                        "reason": user_input.strip(),
                    },
                }
            )

    return _deduplicate_tool_calls(tool_calls)


def execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    user_input: str,
    expert_name: str,
) -> list[dict[str, Any]]:
    """Thực thi tool thật, chuẩn hóa tham số và tận dụng Case Memory cache."""
    results: list[dict[str, Any]] = []
    customer_id = CASE_MEMORY.extract_and_update_customer(user_input) or "KH001"

    for call in tool_calls:
        if not isinstance(call, dict):
            continue

        tool_name = call.get("tool")
        raw_args = call.get("args", {})
        args = dict(raw_args) if isinstance(raw_args, dict) else {}
        func = TOOL_FUNCTIONS.get(tool_name)

        if not tool_name or func is None:
            results.append(
                {
                    "tool": tool_name or "unknown",
                    "args": args,
                    "result": {"error": "Tool không tồn tại hoặc chưa được đăng ký."},
                    "from_cache": False,
                }
            )
            continue

        try:
            if tool_name == "query_policy":
                topic = args.get("topic")
                if not isinstance(topic, str) or len(topic.strip()) < 10:
                    args["topic"] = user_input.strip()
                args["expert_name"] = expert_name
                args["top_k"] = 3

            if (
                "customer_id" in func.__code__.co_varnames
                and "customer_id" not in args
            ):
                args["customer_id"] = customer_id

            cached = CASE_MEMORY.get_cached_tool_result(tool_name, args)
            if cached is not None:
                results.append(
                    {
                        "tool": tool_name,
                        "args": args,
                        "result": cached,
                        "from_cache": True,
                    }
                )
                continue

            result = func(**args)
            CASE_MEMORY.cache_tool_result(tool_name, args, result)
            results.append(
                {
                    "tool": tool_name,
                    "args": args,
                    "result": result,
                    "from_cache": False,
                }
            )
        except Exception as error:
            results.append(
                {
                    "tool": tool_name,
                    "args": args,
                    "result": {"error": str(error)},
                    "from_cache": False,
                }
            )

    return results


def _format_tool_context(tool_results: list[dict[str, Any]]) -> str:
    """Định dạng kết quả tool thành context rõ ràng cho Expert."""
    blocks: list[str] = []

    for index, item in enumerate(tool_results, start=1):
        result_text = json.dumps(
            item.get("result"),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        cache_note = " (lấy từ cache)" if item.get("from_cache") else ""
        blocks.append(
            f"[TOOL {index}: {item.get('tool')}{cache_note}]\n"
            f"Tham số: {json.dumps(item.get('args', {}), ensure_ascii=False, default=str)}\n"
            f"Kết quả:\n{result_text}"
        )

    return "\n\n".join(blocks)


def call_expert(
    expert_name: str,
    user_input: str,
    use_rag: bool = True,
) -> dict[str, Any]:
    """Gọi một Expert: memory → tool/RAG (nếu bật) → khuyến nghị có căn cứ."""
    system_prompt = EXPERT_PROMPTS.get(expert_name)
    if not system_prompt:
        return {
            "text": f"[Lỗi: không tìm thấy Expert '{expert_name}']",
            "tool_calls": [],
        }

    memory_context = CASE_MEMORY.build_context_prefix()
    contextualized_input = f"{memory_context}{user_input}"

    tool_calls = decide_tool_calls(expert_name, user_input, use_rag=use_rag)
    tool_results = execute_tool_calls(tool_calls, user_input, expert_name)
    tool_context = _format_tool_context(tool_results)

    rag_rule = (
        """1. Dữ liệu từ query_policy và các tool là nguồn sự thật ưu tiên.
2. Không tự tạo lãi suất, DTI/LTV tối đa, ngưỡng KYC/AML, điều luật, SLA hoặc
   cấp phê duyệt không xuất hiện trong dữ liệu tool.
3. Khi dữ liệu tool và kiến thức tổng quát mâu thuẫn, phải dùng dữ liệu tool.
4. Nếu kho kiến thức chưa có thông tin, ghi rõ "Chưa có thông tin trong kho kiến thức".
5. Khi dùng RAG, ghi nguồn theo dạng: Tên file — Tên mục."""
        if use_rag
        else """1. RAG (tra cứu kho kiến thức nội bộ) đang TẮT cho yêu cầu này.
2. Trả lời dựa trên kiến thức tổng quát về nghiệp vụ ngân hàng, không trích
   dẫn file/mục cụ thể vì không có dữ liệu tra cứu.
3. Ghi rõ ở đầu câu trả lời: "Lưu ý: câu trả lời này KHÔNG tra cứu quy định
   nội bộ (RAG đang tắt), chỉ mang tính tham khảo chung."."""
    )

    enriched_input = f"""
{contextualized_input}

[DỮ LIỆU TỪ TOOL VÀ KHO KIẾN THỨC]
{tool_context if tool_context else "Không có dữ liệu tool."}

QUY TẮC BẮT BUỘC:
{rag_rule}
6. Chỉ trả lời trong phạm vi chuyên môn của {EXPERT_DISPLAY_NAMES.get(expert_name, expert_name)}.
7. Đây là khuyến nghị hỗ trợ quyết định, không phải quyết định phê duyệt cuối cùng.

Hãy đưa ra ý kiến ngắn gọn, cụ thể và có căn cứ nguồn.
"""

    try:
        text = call_fpt_model(
            system_prompt=system_prompt,
            user_message=enriched_input,
            max_tokens=4000,
        )
    except Exception as error:
        text = f"[Lỗi khi gọi {expert_name} Expert: {error}]"

    CASE_MEMORY.experts_consulted.add(expert_name)
    return {"text": text, "tool_calls": tool_results}


def call_experts_parallel(
    expert_names: list[str],
    task_plan: dict[str, str],
    use_rag: bool = True,
) -> dict[str, dict[str, Any]]:
    """Gọi nhiều Expert song song, mỗi Expert nhận sub-task riêng."""
    results: dict[str, dict[str, Any]] = {}

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(len(expert_names), 1)
    ) as executor:
        future_to_expert = {
            executor.submit(
                call_expert, name, task_plan.get(name, ""), use_rag
            ): name
            for name in expert_names
        }

        for future in concurrent.futures.as_completed(future_to_expert):
            name = future_to_expert[future]
            try:
                results[name] = future.result()
            except Exception as error:
                results[name] = {
                    "text": f"[Lỗi khi gọi {name}: {error}]",
                    "tool_calls": [],
                }

    return results


def contains_risk(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in RISK_KEYWORDS)


def _summarize_tool_result(call: dict[str, Any]) -> str:
    """Tạo trace ngắn, tránh đổ toàn bộ chunk RAG lên phần trả lời chính."""
    result = call.get("result")

    if call.get("tool") == "query_policy" and isinstance(result, dict):
        sources = result.get("sources", [])
        if sources:
            source_names = [
                f"{source.get('source')} — {source.get('heading')}"
                for source in sources
            ]
            return "Nguồn: " + "; ".join(source_names)
        return str(result.get("result", "Không tìm thấy nguồn phù hợp."))

    if isinstance(result, dict) and "error" in result:
        return f"Lỗi: {result['error']}"

    text = str(result)
    return text if len(text) <= 350 else text[:347] + "..."


def format_tool_trace(expert_outputs: dict[str, dict[str, Any]]) -> str:
    """Hiển thị tool call ngắn gọn trên UI."""
    lines: list[str] = []

    for expert, data in expert_outputs.items():
        for call in data.get("tool_calls", []):
            cache_note = " [cache]" if call.get("from_cache") else ""
            lines.append(
                f"🔧 {EXPERT_DISPLAY_NAMES.get(expert, expert)} đã gọi "
                f"`{call.get('tool')}({call.get('args', {})})`{cache_note} → "
                f"{_summarize_tool_result(call)}"
            )

    return "\n".join(lines) + "\n\n" if lines else ""


def format_final_answer(
    user_input: str,
    experts_called: list[str],
    content: str,
    tool_trace: str,
    use_risk_check: bool = True,
) -> str:
    experts_str = ", ".join(
        EXPERT_DISPLAY_NAMES.get(expert, expert) for expert in experts_called
    )
    trace_line = f"🔍 Đã hỏi ý kiến: {experts_str}\n\n"
    warning = ""
    if use_risk_check and (contains_risk(user_input) or contains_risk(content)):
        warning = RISK_WARNING
    return trace_line + tool_trace + warning + content


def _build_synthesis_evidence(expert_outputs: dict[str, dict[str, Any]]) -> str:
    """Đưa bằng chứng tool trực tiếp cho Synthesis Agent để giảm hallucination."""
    blocks: list[str] = []

    for expert, data in expert_outputs.items():
        for call in data.get("tool_calls", []):
            result = call.get("result")
            blocks.append(
                f"--- {EXPERT_DISPLAY_NAMES.get(expert, expert)} / {call.get('tool')} ---\n"
                + json.dumps(result, ensure_ascii=False, indent=2, default=str)
            )

    return "\n\n".join(blocks)


def synthesize_response(
    user_input: str,
    expert_outputs: dict[str, dict[str, Any]],
) -> str:
    combined = "\n\n".join(
        f"--- Ý kiến từ {EXPERT_DISPLAY_NAMES.get(name, name)} ---\n{data['text']}"
        for name, data in expert_outputs.items()
    )
    evidence = _build_synthesis_evidence(expert_outputs)

    synthesis_prompt = f"""
Yêu cầu gốc:
{user_input}

Ý kiến của các Expert:
{combined}

Dữ liệu gốc từ Tool/RAG — đây là nguồn sự thật ưu tiên (có thể rỗng nếu RAG
đang tắt cho yêu cầu này):
{evidence}

QUY TẮC TỔNG HỢP BẮT BUỘC:
1. Không thêm con số, lãi suất, điều luật, ngưỡng KYC/AML, SLA hoặc cấp phê
   duyệt nào không có trong dữ liệu Tool/RAG (nếu có).
2. Nếu ý kiến Expert mâu thuẫn với Tool/RAG, phải dùng Tool/RAG.
3. Không tự giả định lãi suất hoặc kỳ hạn để tính khoản trả nợ nếu người dùng
   chưa cung cấp và tool chưa trả về.
4. Nếu thiếu dữ liệu để kết luận, nêu rõ dữ liệu còn thiếu; không suy đoán.
5. Giữ nguyên nguồn file và tên mục khi trích dẫn chính sách (nếu có).
6. Tổng hợp thành một khuyến nghị duy nhất, mạch lạc và ngắn gọn.
7. Kết thúc chính xác bằng câu:
   "Khuyến nghị này cần cán bộ có thẩm quyền xem xét và phê duyệt cuối cùng."
"""

    try:
        return call_fpt_model(
            system_prompt=ORCHESTRATOR_PROMPT,
            user_message=synthesis_prompt,
            max_tokens=5000,
        )
    except Exception as error:
        return (
            f"Không thể tổng hợp tự động do lỗi: {error}\n\n"
            "Khuyến nghị này cần cán bộ có thẩm quyền xem xét và phê duyệt cuối cùng."
        )


def run_orchestrator(
    user_input: str,
    use_rag: bool = True,
    use_risk_check: bool = True,
) -> str:
    """
    use_rag: bật/tắt tra cứu query_policy cho mọi Expert trong lần chạy này.
    use_risk_check: bật/tắt khối cảnh báo rủi ro ở đầu câu trả lời.
    Cả 2 cờ chỉ ảnh hưởng đến lần gọi này, không đổi state toàn cục — an toàn
    khi nhiều người dùng demo song song với cấu hình khác nhau.
    """
    global LAST_RUN_LOG

    t_start = time_module.time()

    CASE_MEMORY.extract_and_update_customer(user_input)
    CASE_MEMORY.extract_facts(user_input)
    CASE_MEMORY.add_message("Cán bộ", user_input)

    experts_to_call = decide_experts_fast(user_input)
    task_plan = planner_decompose(user_input, experts_to_call)
    t_routing = time_module.time()

    expert_outputs = call_experts_parallel(experts_to_call, task_plan, use_rag=use_rag)
    t_experts = time_module.time()

    tool_trace = format_tool_trace(expert_outputs)

    if len(expert_outputs) == 1:
        content = list(expert_outputs.values())[0]["text"]
        if not content.rstrip().endswith(
            "Khuyến nghị này cần cán bộ có thẩm quyền xem xét và phê duyệt cuối cùng."
        ):
            content += (
                "\n\nKhuyến nghị này cần cán bộ có thẩm quyền xem xét "
                "và phê duyệt cuối cùng."
            )
        synthesis_used = False
    else:
        content = synthesize_response(user_input, expert_outputs)
        synthesis_used = True

    t_end = time_module.time()

    is_risk = use_risk_check and (contains_risk(user_input) or contains_risk(content))
    CASE_MEMORY.add_message("Hệ thống", content)

    all_tool_calls: list[dict[str, Any]] = []
    for expert, data in expert_outputs.items():
        for call in data.get("tool_calls", []):
            all_tool_calls.append({"expert": expert, **call})

    LAST_RUN_LOG = {
        "user_input": user_input,
        "experts_called": list(expert_outputs.keys()),
        "task_plan": task_plan,
        "tool_calls": all_tool_calls,
        "synthesis_used": synthesis_used,
        "risk_flagged": is_risk,
        "memory_state": CASE_MEMORY.get_summary(),
        "timings": {
            "routing_sec": round(t_routing - t_start, 2),
            "experts_sec": round(t_experts - t_routing, 2),
            "synthesis_sec": (
                round(t_end - t_experts, 2) if synthesis_used else 0
            ),
            "total_sec": round(t_end - t_start, 2),
        },
        "settings_used": {"use_rag": use_rag, "use_risk_check": use_risk_check},
    }

    memory_badge = (
        "🧠 Case Memory: đang xử lý hồ sơ "
        f"**{CASE_MEMORY.current_customer_id or 'chưa xác định'}** | "
        f"{len(CASE_MEMORY.tool_results_cache)} dữ liệu đã cache\n\n"
    )

    return memory_badge + format_final_answer(
        user_input=user_input,
        experts_called=list(expert_outputs.keys()),
        content=content,
        tool_trace=tool_trace,
        use_risk_check=use_risk_check,
    )


# ===== SINGLE-AGENT BASELINE (để so sánh) =====

SINGLE_AGENT_PROMPT = """
Bạn là trợ lý AI ngân hàng, hỗ trợ cán bộ tín dụng trả lời các câu hỏi nghiệp vụ chung.
Trả lời ngắn gọn, hữu ích, dựa trên kiến thức tổng quát về ngân hàng.
"""


def run_single_agent_baseline(user_input: str) -> str:
    """Baseline: một lần gọi model, không routing, tool, RAG hoặc risk check."""
    return call_fpt_model(
        system_prompt=SINGLE_AGENT_PROMPT,
        user_message=user_input,
        max_tokens=2000,
    )
