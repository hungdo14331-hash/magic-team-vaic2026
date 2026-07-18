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


def query_policy(topic: str) -> dict:
    """Tra cứu quy định nội bộ liên quan (bản đơn giản, sẽ nâng cấp bằng RAG ở Giai đoạn 3)."""
    policies = {
        "dti": "Ngưỡng DTI an toàn tối đa 50%, trường hợp đặc biệt có thể xét đến 60% nếu có tài sản đảm bảo tốt.",
        "ltv": "Tỷ lệ cho vay trên giá trị tài sản (LTV) tối đa 80% đối với bất động sản.",
        "kyc": "Giao dịch trên 1 tỷ VNĐ yêu cầu KYC nâng cao: xác minh nguồn gốc thu nhập, mục đích sử dụng vốn.",
        "approval_flow": "Khoản vay trên 1.5 tỷ VNĐ cần trình Hội sở phê duyệt, không thể duyệt ở cấp chi nhánh.",
    }
    return {"topic": topic, "content": policies.get(topic, "Chưa có dữ liệu quy định cho chủ đề này.")}


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