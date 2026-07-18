# agents/orchestrator.py
import concurrent.futures
import json
import re
import time as time_module
from tools.memory import CaseMemory

# Case Memory toàn cục — 1 phiên làm việc
CASE_MEMORY = CaseMemory()

# Biến toàn cục lưu lại log của lần chạy gần nhất — dùng cho Dashboard
LAST_RUN_LOG = {
    "user_input": "",
    "experts_called": [],
    "tool_calls": [],
    "timings": {},
    "risk_flagged": False,
}
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
    SYSTEM_PROMPTS,
)

EXPERT_PROMPTS = SYSTEM_PROMPTS

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

def planner_decompose(user_input: str, experts_to_call: list) -> dict:
    """
    Planner Agent thật: viết ra sub-task cụ thể cho từng Expert đã được chọn,
    thay vì để mỗi Expert tự suy đoán phải làm gì từ câu hỏi gốc.
    Nếu model lỗi/timeout, fallback về sub-task mặc định (không bao giờ crash demo).
    """
    if len(experts_to_call) <= 1:
        # Không cần phân rã nếu chỉ 1 Expert — sub-task = câu hỏi gốc
        return {e: user_input for e in experts_to_call}

    expert_names_str = ", ".join(experts_to_call)
    planner_prompt = f"""
Bạn là Planner Agent. Yêu cầu của cán bộ: "{user_input}"

Các Expert sẽ tham gia: {expert_names_str}

Với MỖI Expert, hãy viết 1 câu mô tả CHÍNH XÁC nhiệm vụ của Expert đó cần làm cho yêu cầu này
(không phải lặp lại nguyên văn câu hỏi — hãy phân rã theo đúng chuyên môn riêng).

Trả lời DUY NHẤT bằng JSON dạng object, không giải thích:
{{"credit": "nhiệm vụ cụ thể...", "legal": "nhiệm vụ cụ thể...", ...}}
(chỉ liệt kê đúng các Expert trong danh sách: {expert_names_str})
"""
    response = call_fpt_model(
        system_prompt="Bạn chỉ trả JSON, không giải thích gì thêm.",
        user_message=planner_prompt,
        max_tokens=600,
    )
    try:
        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        plan = json.loads(json_match.group(0)) if json_match else {}
        # Đảm bảo đủ sub-task cho mọi Expert, fallback nếu Planner bỏ sót
        return {e: plan.get(e, user_input) for e in experts_to_call}
    except Exception:
        # Fallback an toàn: mỗi Expert nhận nguyên câu hỏi gốc — demo không bao giờ crash
        return {e: user_input for e in experts_to_call}

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
    """Bước 2: Python thực thi tool thật, có cache từ Case Memory."""
    results = []
    customer_id = CASE_MEMORY.extract_and_update_customer(user_input)
    if not customer_id:
        customer_id = "KH001"  # fallback demo

    for call in tool_calls:
        tool_name = call.get("tool")
        args = call.get("args", {})
        func = TOOL_FUNCTIONS.get(tool_name)
        if not func:
            continue

        try:
            if "customer_id" in func.__code__.co_varnames and "customer_id" not in args:
                args["customer_id"] = customer_id

            # Kiểm tra cache trước — tiết kiệm thời gian nếu đã tra cứu rồi
            cached = CASE_MEMORY.get_cached_tool_result(tool_name, args)
            if cached is not None:
                results.append({"tool": tool_name, "args": args, "result": cached, "from_cache": True})
                continue

            result = func(**args)
            CASE_MEMORY.cache_tool_result(tool_name, args, result)
            results.append({"tool": tool_name, "args": args, "result": result, "from_cache": False})
        except Exception as e:
            results.append({"tool": tool_name, "args": args, "result": {"error": str(e)}, "from_cache": False})

    return results
def call_expert(expert_name: str, user_input: str) -> dict:
    """Gọi 1 Expert: memory context -> quyết định tool -> thực thi -> viết khuyến nghị."""
    system_prompt = EXPERT_PROMPTS.get(expert_name)
    if not system_prompt:
        return {"text": f"[Lỗi: không tìm thấy Expert '{expert_name}']", "tool_calls": []}

    # Chèn ngữ cảnh case đang xử lý
    memory_context = CASE_MEMORY.build_context_prefix()
    contextualized_input = memory_context + user_input

    tool_calls = decide_tool_calls(expert_name, contextualized_input)
    tool_results = execute_tool_calls(tool_calls, user_input) if tool_calls else []

    if tool_results:
        tool_context = "\n".join(
            f"- Đã gọi {r['tool']}({r['args']}) → Kết quả: {r['result']}"
            + (" [từ cache phiên này]" if r.get("from_cache") else "")
            for r in tool_results
        )
        enriched_input = f"{contextualized_input}\n\n[DỮ LIỆU TỪ HỆ THỐNG]\n{tool_context}\n\nDựa trên dữ liệu trên, hãy đưa khuyến nghị cụ thể."
    else:
        enriched_input = contextualized_input

    text = call_fpt_model(system_prompt=system_prompt, user_message=enriched_input, max_tokens=2000)
    CASE_MEMORY.experts_consulted.add(expert_name)
    return {"text": text, "tool_calls": tool_results}
def call_experts_parallel(expert_names: list, task_plan: dict) -> dict:
    """Gọi nhiều Expert CÙNG LÚC, mỗi Expert nhận đúng sub-task Planner đã giao."""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(len(expert_names), 1)) as executor:
        future_to_expert = {
            executor.submit(call_expert, name, task_plan.get(name, "")): name
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

QUAN TRỌNG: Nếu các Expert đưa ra số liệu KHÁC NHAU cho cùng 1 phép tính (VD: DTI), hãy CHỌN MỘT con số hợp lý nhất, KHÔNG liệt kê nhiều con số mâu thuẫn nhau. Không hiển thị quá trình tính toán từng bước — chỉ đưa kết luận và số liệu cuối cùng.

Hãy tổng hợp thành 1 khuyến nghị DUY NHẤT, mạch lạc, có căn cứ rõ ràng, đúng quy trình ngân hàng, NGẮN GỌN.
Kết thúc bằng: "Khuyến nghị này cần cán bộ có thẩm quyền xem xét và phê duyệt cuối cùng."
"""
    return call_fpt_model(system_prompt=ORCHESTRATOR_PROMPT, user_message=synthesis_prompt, max_tokens=4000)




def run_orchestrator(user_input: str) -> str:
    global LAST_RUN_LOG
    t_start = time_module.time()

    # Cập nhật Case Memory TRƯỚC khi routing
    CASE_MEMORY.extract_and_update_customer(user_input)
    CASE_MEMORY.extract_facts(user_input)
    CASE_MEMORY.add_message("Cán bộ", user_input)

    experts_to_call = decide_experts_fast(user_input)
    task_plan = planner_decompose(user_input, experts_to_call)
    t_routing = time_module.time()

    expert_outputs = call_experts_parallel(experts_to_call, task_plan)
    t_experts = time_module.time()

    tool_trace = format_tool_trace(expert_outputs)

    if len(expert_outputs) == 1:
        content = list(expert_outputs.values())[0]["text"] + "\n\nKhuyến nghị này cần cán bộ có thẩm quyền xem xét và phê duyệt cuối cùng."
        synthesis_used = False
    else:
        content = synthesize_response(user_input, expert_outputs)
        synthesis_used = True
    t_end = time_module.time()

    is_risk = contains_risk(user_input) or contains_risk(content)
    CASE_MEMORY.add_message("Hệ thống", content)

    all_tool_calls = []
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
            "synthesis_sec": round(t_end - t_experts, 2) if synthesis_used else 0,
            "total_sec": round(t_end - t_start, 2),
        },
    }

    memory_badge = f"🧠 Case Memory: đang xử lý hồ sơ **{CASE_MEMORY.current_customer_id or 'chưa xác định'}** | {len(CASE_MEMORY.tool_results_cache)} dữ liệu đã cache\n\n"
    return memory_badge + format_final_answer(user_input, list(expert_outputs.keys()), content, tool_trace)


# ===== SINGLE-AGENT BASELINE (để so sánh) =====

SINGLE_AGENT_PROMPT = """
Bạn là trợ lý AI ngân hàng, hỗ trợ cán bộ tín dụng trả lời các câu hỏi nghiệp vụ chung.
Trả lời ngắn gọn, hữu ích, dựa trên kiến thức tổng quát về ngân hàng.
"""


def run_single_agent_baseline(user_input: str) -> str:
    """Baseline: 1 lần gọi model duy nhất, không routing, không tool, không RAG, không risk check."""
    return call_fpt_model(system_prompt=SINGLE_AGENT_PROMPT, user_message=user_input, max_tokens=2000)
