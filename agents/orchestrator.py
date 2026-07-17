# agents/orchestrator.py
import concurrent.futures
from tools.fpt_inference import call_fpt_model
from prompts.system_prompts import (
    ORCHESTRATOR_PROMPT,
    SALES_EXPERT_PROMPT,
    OPERATIONS_EXPERT_PROMPT,
    SUPPORT_EXPERT_PROMPT,
    REPORT_EXPERT_PROMPT,
)

EXPERT_PROMPTS = {
    "sales": SALES_EXPERT_PROMPT,
    "operations": OPERATIONS_EXPERT_PROMPT,
    "support": SUPPORT_EXPERT_PROMPT,
    "report": REPORT_EXPERT_PROMPT,
}

ROUTING_KEYWORDS = {
    "sales": ["doanh số", "bán hàng", "chốt đơn", "khách mới", "chuyển đổi", "upsell", "tăng doanh thu", "marketing", "khuyến mãi"],
    "operations": ["quy trình", "vận hành", "tồn kho", "giao hàng", "nhân sự", "chậm trễ", "tự động hóa", "chi phí", "hiệu suất"],
    "support": ["khiếu nại", "phàn nàn", "chăm sóc khách", "hỗ trợ khách", "phản hồi khách"],
    "report": ["báo cáo", "số liệu", "doanh thu", "phân tích", "thống kê", "insight", "biểu đồ"],
}

RISK_KEYWORDS = [
    "giảm giá sâu", "giảm giá mạnh", "xả hàng", "cắt giảm nhân sự", "sa thải",
    "chi tiêu lớn", "đầu tư lớn", "vay vốn", "vay ngân hàng", "nợ",
    "thay đổi chính sách", "tăng giá mạnh", "phá sản", "kiện", "pháp lý",
]

RISK_WARNING = "⚠️ CẢNH BÁO RỦI RO: Khuyến nghị này liên quan đến quyết định có rủi ro cao, chủ doanh nghiệp cần cân nhắc kỹ trước khi áp dụng.\n\n"


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
    experts_str = ", ".join(e.capitalize() + " Expert" for e in experts_called)
    trace_line = f"🔍 Đã hỏi ý kiến: {experts_str}\n\n"
    warning = RISK_WARNING if (contains_risk(user_input) or contains_risk(content)) else ""
    return trace_line + warning + content


def synthesize_response(user_input: str, expert_outputs: dict) -> str:
    combined = "\n\n".join(
        f"--- Ý kiến từ {name.upper()} EXPERT ---\n{output}"
        for name, output in expert_outputs.items()
    )
    synthesis_prompt = f"""
Yêu cầu gốc của người dùng: "{user_input}"

Dưới đây là ý kiến từ các Expert:
{combined}

Hãy tổng hợp thành 1 khuyến nghị DUY NHẤT, mạch lạc, dễ hành động, ngắn gọn.
Kết thúc bằng câu hỏi: "Bạn thấy khuyến nghị này thế nào? Có muốn điều chỉnh không?"
"""
    return call_fpt_model(system_prompt=ORCHESTRATOR_PROMPT, user_message=synthesis_prompt, max_tokens=3000)


def run_orchestrator(user_input: str) -> str:
    experts_to_call = decide_experts_fast(user_input)
    expert_outputs = call_experts_parallel(experts_to_call, user_input)

    if len(expert_outputs) == 1:
        content = list(expert_outputs.values())[0] + "\n\nBạn thấy khuyến nghị này thế nào? Có muốn điều chỉnh không?"
    else:
        content = synthesize_response(user_input, expert_outputs)

    return format_final_answer(user_input, list(expert_outputs.keys()), content)