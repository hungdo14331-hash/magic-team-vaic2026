# agents/orchestrator.py
import concurrent.futures
import json
import re
from tools.fpt_inference import call_fpt_model
from tools.banking_tools import (
    check_credit_score,
    query_customer_profile,
    calculate_loan_eligibility,
    query_policy,
    create_approval_ticket,
)
from prompts.system_prompts import (
    ORCHESTRATOR_PROMPT,
    CREDIT_EXPERT_PROMPT,
    LEGAL_COMPLIANCE_EXPERT_PROMPT,
    PRODUCT_EXPERT_PROMPT,
    OPERATIONS_EXPERT_PROMPT,
)

EXPERT_PROMPTS = {
    "credit": CREDIT_EXPERT_PROMPT,
    "legal": LEGAL_COMPLIANCE_EXPERT_PROMPT,
    "product": PRODUCT_EXPERT_PROMPT,
    "operations": OPERATIONS_EXPERT_PROMPT,
}

ROUTING_KEYWORDS = {
    "credit": ["vay", "tín dụng", "hồ sơ vay", "trả nợ", "cic", "điểm tín dụng", "dti", "hạn mức", "nợ xấu"],
    "legal": ["kyc", "aml", "tuân thủ", "quy định", "pháp lý", "rửa tiền", "nhnn", "báo cáo giao dịch"],
    "product": ["sản phẩm", "lãi suất", "thẻ", "tiết kiệm", "bảo hiểm", "gói vay", "ưu đãi"],
    "operations": ["quy trình", "phê duyệt", "thủ tục", "sla", "thời gian xử lý", "luồng duyệt"],
}

RISK_KEYWORDS = [
    "nợ xấu", "vượt hạn mức", "rửa tiền", "vi phạm quy định", "từ chối hồ sơ",
    "khách hàng lớn", "ngoại lệ chính sách", "giao dịch lớn", "dti cao", "bất thường",
]

RISK_WARNING = "⚠️ CẢNH BÁO RỦI RO: Yêu cầu này liên quan đến quyết định có rủi ro cao hoặc cần tuân thủ nghiêm ngặt, cần cán bộ có thẩm quyền xem xét kỹ trước khi phê duyệt.\n\n"

# Tool khả dụng cho từng Expert
EXPERT_TOOLS = {
    "credit": ["check_credit_score", "query_customer_profile", "calculate_loan_eligibility"],
    "legal": ["query_policy"],
    "product": ["query_policy"],
    "operations": ["create_approval_ticket", "query_policy"],
}

TOOL_FUNCTIONS = {
    "check_credit_score": check_credit_score,
    "query_customer_profile": query_customer_profile,
    "calculate_loan_eligibility": calculate_loan_eligibility,
    "query_policy": query_policy,
    "create_approval_ticket": create_approval_ticket,
}


def decide_experts_fast(user_input: str) -> list:
    lowered = user_input.lower()
    matched = [expert for expert, keywords in ROUTING_KEYWORDS.items() if any(kw in lowered for kw in keywords)]
    return matched if matched else list(EXPERT_PROMPTS.keys())


def extract_customer_id(text: str) -> str:
    """Tìm mã khách hàng dạng KH001, KH002... trong câu hỏi."""
    match = re.search(r"KH\d{3,}", text.upper())
    return match.group(0) if match else "KH001"  # fallback mặc định để demo luôn chạy được


def decide_tool_calls(expert_name: str, user_input: str) -> list:
    """Bước 1: hỏi model Expert này cần gọi tool nào, với tham số gì — trả về JSON."""
    available_tools = EXPERT_TOOLS.get(expert_name, [])
    if not available_tools:
        return []

    tool_prompt = f"""
Bạn là {expert_name} Expert. Yêu cầu của người dùng: "{user_input}"

Các tool khả dụng: {', '.join(available_tools)}
- check_credit_score(customer_id): tra CIC
- query_customer_profile(customer_id): tra thu nhập, nợ hiện tại
- calculate_loan_eligibility(income, existing_debt_monthly, new_loan_monthly_payment): tính DTI
- query_policy(topic): tra quy định, topic là 1 trong: dti, ltv, kyc, approval_flow
- create_approval_ticket(customer_id, decision, reason): tạo phiếu trình

Trả lời DUY NHẤT bằng JSON dạng list, không giải thích gì thêm:
[{{"tool": "ten_tool", "args": {{...tham số...}}}}]

Nếu không cần gọi tool nào, trả về: []
"""
    response = call_fpt_model(system_prompt="Bạn chỉ trả JSON, không giải thích.", user_message=tool_prompt, max_tokens=500)
    try:
        json_match = re.search(r"\[.*\]", response, re.DOTALL)
        return json.loads(json_match.group(0)) if json_match else []
    except Exception:
        return []  # nếu model trả sai định dạng, bỏ qua tool, vẫn tiếp tục chạy (không crash demo)


def execute_tool_calls(tool_calls: list, user_input: str) -> list:
    """Bước 2: Python thực thi tool thật."""
    results = []
    customer_id = extract_customer_id(user_input)
    for call in tool_calls:
        tool_name = call.get("tool")
        args = call.get("args", {})
        func = TOOL_FUNCTIONS.get(tool_name)
        if not func:
            continue
        try:
            if "customer_id" in func.__code__.co_varnames and "customer_id" not in args:
                args["customer_id"] = customer_id
            result = func(**args)
            results.append({"tool": tool_name, "args": args, "result": result})
        except Exception as e:
            results.append({"tool": tool_name, "args": args, "result": {"error": str(e)}})
    return results


def call_expert(expert_name: str, user_input: str) -> dict:
    """Gọi 1 Expert: quyết định tool -> thực thi tool -> viết khuyến nghị cuối dựa trên kết quả tool."""
    system_prompt = EXPERT_PROMPTS.get(expert_name)
    if not system_prompt:
        return {"text": f"[Lỗi: không tìm thấy Expert '{expert_name}']", "tool_calls": []}

    tool_calls = decide_tool_calls(expert_name, user_input)
    tool_results = execute_tool_calls(tool_calls, user_input) if tool_calls else []

    if tool_results:
        tool_context = "\n".join(
            f"- Đã gọi {r['tool']}({r['args']}) → Kết quả: {r['result']}" for r in tool_results
        )
        enriched_input = f"{user_input}\n\n[DỮ LIỆU TỪ HỆ THỐNG]\n{tool_context}\n\nDựa trên dữ liệu trên, hãy đưa khuyến nghị cụ thể."
    else:
        enriched_input = user_input

    text = call_fpt_model(system_prompt=system_prompt, user_message=enriched_input, max_tokens=2000)
    return {"text": text, "tool_calls": tool_results}


def call_experts_parallel(expert_names: list, user_input: str) -> dict:
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(len(expert_names), 1)) as executor:
        future_to_expert = {
            executor.submit(call_expert, name, user_input): name
            for name in expert_names
        }
        for future in concurrent.futures.as_completed(future_to_expert):
            name = future_to_expert[future]
            try:
                results[name] = future.result()
            except Exception as e:
                results[name] = {"text": f"[Lỗi khi gọi {name}: {str(e)}]", "tool_calls": []}
    return results


def contains_risk(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in RISK_KEYWORDS)


def format_tool_trace(expert_outputs: dict) -> str:
    """Hiển thị tool call trên UI."""
    lines = []
    name_map = {"credit": "Credit Expert", "legal": "Legal & Compliance Expert", "product": "Product Expert", "operations": "Operations Expert"}
    for expert, data in expert_outputs.items():
        for call in data.get("tool_calls", []):
            lines.append(f"🔧 {name_map.get(expert, expert)} đã gọi: `{call['tool']}({call['args']})` → {call['result']}")
    return "\n".join(lines) + "\n\n" if lines else ""


def format_final_answer(user_input: str, experts_called: list, content: str, tool_trace: str) -> str:
    name_map = {"credit": "Credit Expert", "legal": "Legal & Compliance Expert", "product": "Product Expert", "operations": "Operations Expert"}
    experts_str = ", ".join(name_map.get(e, e) for e in experts_called)
    trace_line = f"🔍 Đã hỏi ý kiến: {experts_str}\n\n"
    warning = RISK_WARNING if (contains_risk(user_input) or contains_risk(content)) else ""
    return trace_line + tool_trace + warning + content


def synthesize_response(user_input: str, expert_outputs: dict) -> str:
    combined = "\n\n".join(
        f"--- Ý kiến từ {name.upper()} EXPERT ---\n{data['text']}"
        for name, data in expert_outputs.items()
    )
    synthesis_prompt = f"""
Yêu cầu gốc: "{user_input}"

Dưới đây là ý kiến từ các Expert:
{combined}

Hãy tổng hợp thành 1 khuyến nghị DUY NHẤT, mạch lạc, có căn cứ rõ ràng, đúng quy trình ngân hàng.
Kết thúc bằng: "Khuyến nghị này cần cán bộ có thẩm quyền xem xét và phê duyệt cuối cùng."
"""
    return call_fpt_model(system_prompt=ORCHESTRATOR_PROMPT, user_message=synthesis_prompt, max_tokens=3000)


def run_orchestrator(user_input: str) -> str:
    experts_to_call = decide_experts_fast(user_input)
    expert_outputs = call_experts_parallel(experts_to_call, user_input)
    tool_trace = format_tool_trace(expert_outputs)

    if len(expert_outputs) == 1:
        content = list(expert_outputs.values())[0]["text"] + "\n\nKhuyến nghị này cần cán bộ có thẩm quyền xem xét và phê duyệt cuối cùng."
    else:
        content = synthesize_response(user_input, expert_outputs)

    return format_final_answer(user_input, list(expert_outputs.keys()), content, tool_trace)