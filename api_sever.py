# api_server.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time

from agents.orchestrator import run_orchestrator, run_single_agent_baseline
import agents.orchestrator as orchestrator_module

app = FastAPI(title="SHB Digital Expert Agents API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


EXPERTS_INFO = [
    {"id": "credit", "name": "Credit Expert", "specialty": "Thẩm định tín dụng, DTI/LTV, phân loại nhóm nợ", "icon": "credit-card"},
    {"id": "legal", "name": "Legal & Compliance Expert", "specialty": "Tuân thủ NHNN, KYC/AML", "icon": "shield-check"},
    {"id": "product", "name": "Product Expert", "specialty": "Tư vấn sản phẩm, cross-sell", "icon": "package"},
    {"id": "operations", "name": "Operations Expert", "specialty": "Luồng phê duyệt, SLA, thủ tục", "icon": "settings"},
]


@app.get("/api/experts")
def get_experts():
    return {"experts": EXPERTS_INFO}


@app.post("/api/chat")
def chat(req: ChatRequest):
    response_text = run_orchestrator(req.message)
    return {"response": response_text, "dashboard": orchestrator_module.LAST_RUN_LOG}


@app.post("/api/compare")
def compare(req: ChatRequest):
    t0 = time.time()
    single = run_single_agent_baseline(req.message)
    t1 = time.time()
    multi = run_orchestrator(req.message)
    t2 = time.time()
    return {
        "single_agent": {"text": single, "time_sec": round(t1 - t0, 2)},
        "multi_agent": {"text": multi, "time_sec": round(t2 - t1, 2), "dashboard": orchestrator_module.LAST_RUN_LOG},
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}
