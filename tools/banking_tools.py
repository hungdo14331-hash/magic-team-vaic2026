import random
from tools.rag import retrieve_context
from tools.rag import retrieve_context

# tools/banking_tools.py
"""
Mock banking tools — dữ liệu giả lập vì không có quyền truy cập hệ thống SHB thật.
Mỗi hàm mô phỏng 1 API call thật mà Expert có thể gọi để lấy dữ liệu/thực thi hành động.
"""

import random

# Dữ liệu khách hàng mẫu (mock database)
MOCK_CUSTOMERS = {
    "KH001": {
        "name": "Nguyễn Văn A",
        "income": 45_000_000,
        "existing_debt_monthly": 16_600_000,
        "cic_score": 720,
        "cic_group": 1,
        "years_as_customer": 3,
    },
    "KH002": {
        "name": "Trần Thị B",
        "income": 80_000_000,
        "existing_debt_monthly": 5_000_000,
        "cic_score": 810,
        "cic_group": 1,
        "years_as_customer": 7,
    },
}


def check_credit_score(customer_id: str) -> dict:
    """Tra cứu điểm tín dụng CIC và nhóm nợ của khách hàng."""
    customer = MOCK_CUSTOMERS.get(customer_id)
    if not customer:
        return {"error": f"Không tìm thấy khách hàng {customer_id} trong hệ thống."}
    return {
        "customer_id": customer_id,
        "cic_score": customer["cic_score"],
        "cic_group": customer["cic_group"],
        "note": "Nhóm 1 = nợ đủ tiêu chuẩn, an toàn nhất" if customer["cic_group"] == 1 else "Cần xem xét kỹ",
    }


def query_customer_profile(customer_id: str) -> dict:
    """Tra cứu hồ sơ khách hàng: thu nhập, nợ hiện tại, thâm niên."""
    customer = MOCK_CUSTOMERS.get(customer_id)
    if not customer:
        return {"error": f"Không tìm thấy khách hàng {customer_id} trong hệ thống."}
    return {
        "customer_id": customer_id,
        "name": customer["name"],
        "income_monthly": customer["income"],
        "existing_debt_monthly": customer["existing_debt_monthly"],
        "years_as_customer": customer["years_as_customer"],
    }


def calculate_loan_eligibility(income: float, existing_debt_monthly: float, new_loan_monthly_payment: float) -> dict:
    """Tính tỷ lệ DTI (Debt-to-Income) và kết luận đủ/chưa đủ điều kiện."""
    total_debt = existing_debt_monthly + new_loan_monthly_payment
    dti = round((total_debt / income) * 100, 1) if income > 0 else 0
    eligible = dti <= 50
    return {
        "dti_percent": dti,
        "total_monthly_debt": total_debt,
        "threshold_percent": 50,
        "eligible": eligible,
        "conclusion": "Đủ điều kiện theo DTI" if eligible else f"DTI {dti}% vượt ngưỡng an toàn 50% — cần giải pháp bổ sung",
    }


def query_policy(
    topic: str,
    expert_name: str = "general",
    top_k: int = 3,
) -> dict:
    """
    Tra cứu quy định nội bộ bằng Lightweight RAG.

    Args:
        topic:
            Câu hỏi hoặc chủ đề cần tra cứu.

        expert_name:
            Expert thực hiện tra cứu, ví dụ:
            - credit_expert
            - compliance_expert
            - product_expert
            - operations_expert
            - general

        top_k:
            Số đoạn kiến thức liên quan tối đa cần lấy.

    Returns:
        Dictionary gồm:
        - success: trạng thái truy vấn
        - tool: tên tool
        - query: câu hỏi gốc
        - expert_name: Expert truy vấn
        - result: context kiến thức để đưa vào LLM
        - sources: danh sách nguồn trích dẫn
    """
    if not isinstance(topic, str) or not topic.strip():
        return {
            "success": False,
            "tool": "query_policy",
            "query": topic,
            "expert_name": expert_name,
            "result": "Chủ đề tra cứu không hợp lệ.",
            "sources": [],
        }

    try:
        rag_result = retrieve_context(
            expert_name=expert_name,
            query=topic.strip(),
            top_k=top_k,
        )

        sources = rag_result.get("sources", [])
        context = rag_result.get("context", "")

        if not sources:
            return {
                "success": False,
                "tool": "query_policy",
                "query": topic.strip(),
                "expert_name": expert_name,
                "result": (
                    "Không tìm thấy quy định phù hợp "
                    "trong kho kiến thức nội bộ."
                ),
                "sources": [],
            }

        return {
            "success": True,
            "tool": "query_policy",
            "query": topic.strip(),
            "expert_name": expert_name,
            "result": context,
            "sources": sources,
        }

    except Exception as error:
        return {
            "success": False,
            "tool": "query_policy",
            "query": topic.strip(),
            "expert_name": expert_name,
            "result": f"Lỗi khi tra cứu kho kiến thức: {error}",
            "sources": [],
        }
def create_approval_ticket(customer_id: str, decision: str, reason: str) -> dict:
    """Tạo phiếu trình phê duyệt (mock — trả về ticket ID giả lập)."""
    ticket_id = f"TICKET-{random.randint(10000, 99999)}"
    return {
        "ticket_id": ticket_id,
        "customer_id": customer_id,
        "decision": decision,
        "reason": reason,
        "status": "Đã tạo — chờ cán bộ có thẩm quyền phê duyệt",
    }