# api.py
"""
FastAPI wrapper cho SHB Digital Expert Agents.

BẢN CẬP NHẬT so với bản trước:
1. /api/chat và /api/compare nhận thêm 2 cờ tùy chọn: use_rag, use_risk_check
   (mặc định đều True nếu không gửi lên — không phá vỡ Frontend cũ).
2. Thêm GET /api/knowledge-base — đọc 4 file .md trong data/knowledge/, dùng
   cho trang "Kho tri thức".
3. Thêm GET /api/tools — trả về danh sách 5 tool thật kèm mô tả, dùng cho
   trang "Công cụ (Tools)".

Thay thế toàn bộ nội dung file api.py hiện tại bằng file này.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import agents.orchestrator as orchestrator_module
from agents.orchestrator import (
    EXPERT_DISPLAY_NAMES,
    run_orchestrator,
    run_single_agent_baseline,
)

app = FastAPI(
    title="SHB Digital Expert Agents API",
    description="REST API cho hệ multi-agent ngân hàng — VAIC 2026",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: giới hạn lại thành domain Vercel thật trước khi nộp bài
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Schemas =====

class ChatRequest(BaseModel):
    message: str
    use_rag: bool = True
    use_risk_check: bool = True


class ChatResponse(BaseModel):
    response: str
    elapsed_seconds: float
    settings_used: dict[str, bool]


class CompareRequest(BaseModel):
    message: str
    use_rag: bool = True
    use_risk_check: bool = True


class CompareResponse(BaseModel):
    single_agent: dict[str, Any]
    multi_agent: dict[str, Any]


class TraceResponse(BaseModel):
    user_input: str
    experts_called: list[str]
    experts_called_display: list[str]
    task_plan: dict[str, str]
    tool_calls: list[dict[str, Any]]
    synthesis_used: bool
    risk_flagged: bool
    memory_state: dict[str, Any]
    timings: dict[str, Any]
    settings_used: dict[str, bool]
    has_data: bool


class KnowledgeDocument(BaseModel):
    id: str
    title: str
    expert: str
    expert_display_name: str
    content: str


class KnowledgeBaseResponse(BaseModel):
    documents: list[KnowledgeDocument]


class ToolInfo(BaseModel):
    name: str
    description: str
    used_by_experts: list[str]
    used_by_experts_display: list[str]
    parameters: list[str]


class ToolsResponse(BaseModel):
    tools: list[ToolInfo]


# ===== Endpoints =====

@app.get("/")
def root():
    return {"status": "ok", "service": "SHB Digital Expert Agents API"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    """
    Endpoint chính — tương đương tab Chat trong Streamlit.
    use_rag / use_risk_check: bật/tắt THẬT theo từng request, không ảnh hưởng
    request khác đang chạy song song.
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="message không được để trống")

    start = time.time()
    try:
        response_text = run_orchestrator(
            payload.message.strip(),
            use_rag=payload.use_rag,
            use_risk_check=payload.use_risk_check,
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý: {error}") from error
    elapsed = time.time() - start

    return ChatResponse(
        response=response_text,
        elapsed_seconds=round(elapsed, 2),
        settings_used={"use_rag": payload.use_rag, "use_risk_check": payload.use_risk_check},
    )


@app.post("/api/compare", response_model=CompareResponse)
def compare(payload: CompareRequest):
    """Endpoint so sánh — tương đương tab So sánh Multi-Agent vs Single-Agent."""
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="message không được để trống")

    msg = payload.message.strip()

    t0 = time.time()
    try:
        single_result = run_single_agent_baseline(msg)
    except Exception as error:
        single_result = f"[Lỗi Single-Agent: {error}]"
    t1 = time.time()

    try:
        multi_result = run_orchestrator(
            msg,
            use_rag=payload.use_rag,
            use_risk_check=payload.use_risk_check,
        )
    except Exception as error:
        multi_result = f"[Lỗi Multi-Agent: {error}]"
    t2 = time.time()

    return CompareResponse(
        single_agent={
            "response": single_result,
            "elapsed_seconds": round(t1 - t0, 2),
            "features": ["Không tool", "Không RAG", "Không risk check"],
        },
        multi_agent={
            "response": multi_result,
            "elapsed_seconds": round(t2 - t1, 2),
            "features": [
                "Có tool thật" if payload.use_rag else "RAG đang tắt",
                "Có tra cứu quy định (RAG)" if payload.use_rag else "Không tra cứu quy định",
                "Có cảnh báo rủi ro" if payload.use_risk_check else "Cảnh báo rủi ro đang tắt",
            ],
        },
    )


@app.get("/api/trace", response_model=TraceResponse)
def trace():
    """Endpoint dashboard — trả về log của lần chạy /api/chat hoặc /api/compare gần nhất."""
    log = orchestrator_module.LAST_RUN_LOG

    has_data = bool(log["user_input"])

    experts_called_display = [
        EXPERT_DISPLAY_NAMES.get(e, e) for e in log["experts_called"]
    ]

    return TraceResponse(
        user_input=log["user_input"],
        experts_called=log["experts_called"],
        experts_called_display=experts_called_display,
        task_plan=log.get("task_plan", {}),
        tool_calls=log.get("tool_calls", []),
        synthesis_used=log.get("synthesis_used", False),
        risk_flagged=log.get("risk_flagged", False),
        memory_state=log.get("memory_state", {}),
        timings=log.get("timings", {}),
        settings_used=log.get("settings_used", {"use_rag": True, "use_risk_check": True}),
        has_data=has_data,
    )


@app.get("/api/experts")
def list_experts():
    """Danh sách 4 Expert cố định — để frontend render badge/icon tĩnh."""
    return {
        "experts": [
            {"id": "credit", "display_name": "Credit Expert", "icon": "credit-card"},
            {"id": "legal", "display_name": "Legal & Compliance Expert", "icon": "scale"},
            {"id": "product", "display_name": "Product Expert", "icon": "package"},
            {"id": "operations", "display_name": "Operations Expert", "icon": "workflow"},
        ]
    }


# ===== Kho tri thức =====

# Đường dẫn tới thư mục chứa 4 file kiến thức RAG. Đường dẫn tính từ vị trí
# file api.py này (thư mục gốc repo) tới data/knowledge/.
KNOWLEDGE_DIR = Path(__file__).parent / "data" / "knowledge"

KNOWLEDGE_FILES = [
    {"filename": "credit_policy.md", "expert": "credit", "title": "Chính sách Tín dụng"},
    {"filename": "legal_compliance.md", "expert": "legal", "title": "Tuân thủ Pháp lý"},
    {"filename": "products.md", "expert": "product", "title": "Sản phẩm Ngân hàng"},
    {"filename": "operations.md", "expert": "operations", "title": "Quy trình Vận hành"},
]


@app.get("/api/knowledge-base", response_model=KnowledgeBaseResponse)
def knowledge_base():
    """
    Đọc trực tiếp 4 file .md trong data/knowledge/ — đây CHÍNH LÀ kho kiến
    thức RAG thật mà các Expert dùng để tra cứu (query_policy), không phải
    dữ liệu giả lập riêng cho trang này.
    """
    documents: list[KnowledgeDocument] = []

    for file_info in KNOWLEDGE_FILES:
        file_path = KNOWLEDGE_DIR / file_info["filename"]
        try:
            content = file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = f"[Không tìm thấy file {file_info['filename']} trên server.]"
        except Exception as error:
            content = f"[Lỗi khi đọc file: {error}]"

        documents.append(
            KnowledgeDocument(
                id=file_info["expert"],
                title=file_info["title"],
                expert=file_info["expert"],
                expert_display_name=EXPERT_DISPLAY_NAMES.get(
                    file_info["expert"], file_info["expert"]
                ),
                content=content,
            )
        )

    return KnowledgeBaseResponse(documents=documents)


# ===== Công cụ (Tools) =====

TOOLS_METADATA: list[ToolInfo] = [
    ToolInfo(
        name="check_credit_score",
        description="Tra cứu điểm tín dụng CIC và nhóm nợ của khách hàng từ hệ thống mock.",
        used_by_experts=["credit"],
        used_by_experts_display=["Credit Expert"],
        parameters=["customer_id"],
    ),
    ToolInfo(
        name="query_customer_profile",
        description="Tra cứu hồ sơ khách hàng: thu nhập, nợ hiện tại, thâm niên khách hàng.",
        used_by_experts=["credit"],
        used_by_experts_display=["Credit Expert"],
        parameters=["customer_id"],
    ),
    ToolInfo(
        name="calculate_loan_eligibility",
        description="Tính tỷ lệ DTI (Debt-to-Income) và kết luận đủ/chưa đủ điều kiện vay.",
        used_by_experts=["credit"],
        used_by_experts_display=["Credit Expert"],
        parameters=["income", "existing_debt_monthly", "new_loan_monthly_payment"],
    ),
    ToolInfo(
        name="query_policy",
        description="Tra cứu quy định nội bộ bằng RAG (Lightweight Retrieval-Augmented Generation), mỗi Expert dùng đúng kho kiến thức chuyên môn của mình.",
        used_by_experts=["credit", "legal", "product", "operations"],
        used_by_experts_display=[
            "Credit Expert",
            "Legal & Compliance Expert",
            "Product Expert",
            "Operations Expert",
        ],
        parameters=["topic", "expert_name", "top_k"],
    ),
    ToolInfo(
        name="create_approval_ticket",
        description="Tạo phiếu trình phê duyệt (mock — trả về ticket ID giả lập) khi cán bộ yêu cầu lập phiếu.",
        used_by_experts=["operations"],
        used_by_experts_display=["Operations Expert"],
        parameters=["customer_id", "decision", "reason"],
    ),
]


@app.get("/api/tools", response_model=ToolsResponse)
def list_tools():
    """Danh sách 5 tool thật mà hệ thống dùng — dùng cho trang 'Công cụ (Tools)'."""
    return ToolsResponse(tools=TOOLS_METADATA)


# ===== Cài đặt hệ thống (thông tin, không lưu state server-side) =====

@app.get("/api/system-info")
def system_info():
    """
    Thông tin hệ thống chỉ đọc — model đang dùng, số expert, trạng thái kết nối.
    KHÔNG trả về API key hay bất kỳ giá trị bí mật nào.
    """
    model_name = os.getenv("FPT_MODEL_NAME", "chưa cấu hình")
    return {
        "model_name": model_name,
        "experts_count": len(EXPERT_DISPLAY_NAMES),
        "experts": list(EXPERT_DISPLAY_NAMES.values()),
        "api_version": app.version,
        "default_settings": {"use_rag": True, "use_risk_check": True},
        "note": (
            "use_rag và use_risk_check là tham số gửi kèm mỗi request tới "
            "/api/chat hoặc /api/compare, không phải cấu hình lưu trên server."
        ),
    }
