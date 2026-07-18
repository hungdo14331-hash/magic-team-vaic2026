# agents/orchestrator.py
import concurrent.futures
from tools.fpt_inference import call_fpt_model
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


def decide_experts_fast(user_input: str) -> list:
    lowered = user_input.lower()
    matched = [expert for expert, keywords in ROUTING_KEYWORDS.items() if any(kw in lowered for kw in keywords)]
    return matched if matched else list(EXPERT_PROMPTS.keys())


def call_expert(expert_name: str, user_input: str) -> str:
    system_prompt = EXPERT_PROMPTS.get(expert_name)
    if not system_prompt:
        return f"[Lỗi: không tìm thấy Expert '{expert_name}']"
    return call_fpt_model(system_prompt=system_prompt, user_message=user_input, max_tokens=2000)


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
                results[name] = f"[Lỗi khi gọi {name}: {str(e)}]"
    return results


def contains_risk(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in RISK_KEYWORDS)


def format_final_answer(user_input: str, experts_called: list, content: str) -> str:
    name_map = {
        "credit": "Credit Expert",
        "legal": "Legal & Compliance Expert",
        "product": "Product Expert",
        "operations": "Operations Expert",
    }
    experts_str = ", ".join(name_map.get(e, e) for e in experts_called)
    trace_line = f"🔍 Đã hỏi ý kiến: {experts_str}\n\n"
    warning = RISK_WARNING if (contains_risk(user_input) or contains_risk(content)) else ""
    return trace_line + warning + content


def synthesize_response(user_input: str, expert_outputs: dict) -> str:
    combined = "\n\n".join(
        f"--- Ý kiến từ {name.upper()} EXPERT ---\n{output}"
        for name, output in expert_outputs.items()
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

    if len(expert_outputs) == 1:
        content = list(expert_outputs.values())[0] + "\n\nKhuyến nghị này cần cán bộ có thẩm quyền xem xét và phê duyệt cuối cùng."
    else:
        content = synthesize_response(user_input, expert_outputs)

    return format_final_answer(user_input, list(expert_outputs.keys()), content)