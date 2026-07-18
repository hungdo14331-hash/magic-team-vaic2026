# tools/memory.py
"""
Case Memory — quản lý ngữ cảnh hồ sơ đang xử lý xuyên suốt phiên làm việc.
Cho phép cán bộ hỏi tiếp mà không cần nhắc lại thông tin khách hàng.
"""

import re
import time


class CaseMemory:
    """Lưu trữ state của 1 'case' (hồ sơ) đang được xử lý."""

    def __init__(self):
        self.current_customer_id = None
        self.conversation_history = []      # [{role, content, timestamp}]
        self.tool_results_cache = {}        # {tool_name+args: result} — tránh gọi lại tool giống hệt
        self.facts = {}                     # Các dữ kiện đã xác lập: {loan_amount: 2_000_000_000, ...}
        self.experts_consulted = set()      # Expert nào đã tham gia case này

    def extract_and_update_customer(self, text: str):
        """Tìm mã KH trong câu hỏi; nếu có thì cập nhật, nếu không thì giữ mã cũ."""
        match = re.search(r"KH\d{3,}", text.upper())
        if match:
            new_id = match.group(0)
            if new_id != self.current_customer_id:
                self.reset_case()   # Đổi khách hàng → reset case cũ
                self.current_customer_id = new_id
        return self.current_customer_id

    def extract_facts(self, text: str):
        """Trích xuất các dữ kiện số học từ câu hỏi (số tiền vay, thu nhập...)."""
        # Số tiền dạng "2 tỷ", "1.5 tỷ"
        loan_match = re.search(r"vay\s+([\d.,]+)\s*tỷ", text.lower())
        if loan_match:
            amount = float(loan_match.group(1).replace(",", "."))
            self.facts["loan_amount"] = int(amount * 1_000_000_000)

        # Thu nhập dạng "45 triệu/tháng"
        income_match = re.search(r"thu nhập\s+([\d.,]+)\s*triệu", text.lower())
        if income_match:
            amount = float(income_match.group(1).replace(",", "."))
            self.facts["income_monthly"] = int(amount * 1_000_000)

        return self.facts

    def add_message(self, role: str, content: str):
        self.conversation_history.append({
            "role": role,
            "content": content[:500],  # Cắt ngắn để không phình context
            "timestamp": time.strftime("%H:%M:%S"),
        })

    def cache_tool_result(self, tool_name: str, args: dict, result):
        key = f"{tool_name}:{str(sorted(args.items()))}"
        self.tool_results_cache[key] = result

    def get_cached_tool_result(self, tool_name: str, args: dict):
        key = f"{tool_name}:{str(sorted(args.items()))}"
        return self.tool_results_cache.get(key)

    def build_context_prefix(self) -> str:
        """Tạo đoạn ngữ cảnh chèn vào prompt để Expert biết case đang xử lý."""
        if not self.current_customer_id and not self.facts:
            return ""

        parts = ["[NGỮ CẢNH HỒ SƠ ĐANG XỬ LÝ]"]
        if self.current_customer_id:
            parts.append(f"- Khách hàng: {self.current_customer_id}")
        if self.facts.get("loan_amount"):
            parts.append(f"- Số tiền vay đang xét: {self.facts['loan_amount']:,} VNĐ")
        if self.facts.get("income_monthly"):
            parts.append(f"- Thu nhập: {self.facts['income_monthly']:,} VNĐ/tháng")
        if self.tool_results_cache:
            parts.append(f"- Đã tra cứu {len(self.tool_results_cache)} nguồn dữ liệu trong phiên này")
        if self.experts_consulted:
            parts.append(f"- Chuyên gia đã tham gia: {', '.join(self.experts_consulted)}")

        # 2 lượt trao đổi gần nhất
        if len(self.conversation_history) >= 2:
            parts.append("\n[TRAO ĐỔI GẦN NHẤT]")
            for msg in self.conversation_history[-2:]:
                parts.append(f"- {msg['role']}: {msg['content'][:200]}")

        return "\n".join(parts) + "\n\n"

    def reset_case(self):
        """Reset khi chuyển sang khách hàng khác."""
        self.current_customer_id = None
        self.tool_results_cache = {}
        self.facts = {}
        self.experts_consulted = set()
        # Giữ conversation_history để có thể tra cứu lại

    def get_summary(self) -> dict:
        """Tóm tắt state — dùng cho Dashboard."""
        return {
            "customer_id": self.current_customer_id or "Chưa xác định",
            "facts": self.facts,
            "cached_tools": len(self.tool_results_cache),
            "experts_consulted": list(self.experts_consulted),
            "history_length": len(self.conversation_history),
        }