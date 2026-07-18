# api.py
"""
FastAPI wrapper cho SHB Digital Expert Agents.
 
Mục đích: expose lại đúng logic Python đã có sẵn trong agents/orchestrator.py
thành REST endpoint JSON, để Frontend (Next.js/v0) gọi vào qua fetch().
KHÔNG viết lại bất kỳ logic nghiệp vụ nào — chỉ bọc thêm 1 lớp HTTP mỏng.
 
Chạy cùng lúc với Streamlit (2 process khác nhau, đọc chung 1 CASE_MEMORY
module-level vì cùng import agents.orchestrator trong cùng 1 process Python
nếu deploy chung — xem ghi chú CORS/deploy bên dưới).
"""
 
from __future__ import annotations
 
import time
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
    version="1.0.0",
)
 
# CORS mở cho frontend Next.js (đổi allow_origins thành domain Vercel thật khi deploy)
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
 
 
class ChatResponse(BaseModel):
    response: str
    elapsed_seconds: float
 
 
class CompareRequest(BaseModel):
    message: str
 
 
class CompareResponse(BaseModel):
    single_agent: dict[str, Any]
    multi_agent: dict[str, Any]
 
 
class ExpertOutput(BaseModel):
    expert: str
    expert_display_name: str
    text: str
 
 
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
    has_data: bool
 
 
# ===== Endpoints =====
 
@app.get("/")
def root():
    return {"status": "ok", "service": "SHB Digital Expert Agents API"}
 
 
@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    """
    Endpoint chính — tương đương tab Chat trong Streamlit.
    Chạy toàn bộ pipeline: routing -> planner -> experts song song -> synthesis.
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="message không được để trống")
 
    start = time.time()
    try:
        response_text = run_orchestrator(payload.message.strip())
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý: {error}") from error
    elapsed = time.time() - start
 
    return ChatResponse(response=response_text, elapsed_seconds=round(elapsed, 2))
 
 
@app.post("/api/compare", response_model=CompareResponse)
def compare(payload: CompareRequest):
    """
    Endpoint so sánh — tương đương tab So sánh Multi-Agent vs Single-Agent.
    Chạy cả 2 pipeline trên cùng 1 input, trả về song song để frontend hiển thị 2 cột.
    """
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
        multi_result = run_orchestrator(msg)
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
            "features": ["Có tool thật", "Có tra cứu quy định (RAG)", "Có cảnh báo rủi ro"],
        },
    )
 
 
@app.get("/api/trace", response_model=TraceResponse)
def trace():
    """
    Endpoint dashboard — tương đương tab Agent Trace Dashboard.
    Trả về log của lần chạy /api/chat hoặc /api/compare gần nhất.
    Frontend nên gọi lại endpoint này ngay sau khi /api/chat trả về, để refresh dashboard.
    """
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
        has_data=has_data,
    )
 
 
@app.get("/api/experts")
def list_experts():
    """Danh sách 4 Expert cố định — để frontend render badge/icon tĩnh mà không cần hardcode."""
    return {
        "experts": [
            {"id": "credit", "display_name": "Credit Expert", "icon": "credit-card"},
            {"id": "legal", "display_name": "Legal & Compliance Expert", "icon": "scale"},
            {"id": "product", "display_name": "Product Expert", "icon": "package"},
            {"id": "operations", "display_name": "Operations Expert", "icon": "workflow"},
        ]
    }
