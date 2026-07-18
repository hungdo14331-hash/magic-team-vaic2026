# main.py
import streamlit as st
import time
from agents.orchestrator import run_orchestrator, run_single_agent_baseline
import agents.orchestrator as orchestrator_module
from agents.orchestrator import run_orchestrator, run_single_agent_baseline

st.set_page_config(page_title="SHB Digital Expert Agents", page_icon="🏦", layout="wide")

st.title("🏦 SHB Digital Expert Agents")
st.caption("Hội đồng chuyên gia số cho Nghiệp vụ Ngân hàng — VAIC 2026")

tab_chat, tab_compare, tab_dashboard = st.tabs([
    "💬 Chat với Đội ngũ Expert",
    "⚖️ So sánh Multi-Agent vs Single-Agent",
    "📊 Agent Trace Dashboard",
])
with tab_chat:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    user_input = st.chat_input("Nhập yêu cầu nghiệp vụ (VD: thẩm định khoản vay, kiểm tra tuân thủ...)")

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.write(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Đang phối hợp cùng đội ngũ chuyên gia..."):
                start_time = time.time()
                response = run_orchestrator(user_input)
                elapsed = time.time() - start_time
            st.write(response)
            st.caption(f"⏱️ {elapsed:.1f} giây")

        st.session_state.messages.append({"role": "assistant", "content": response})

with tab_compare:
    st.subheader("So sánh trực tiếp: Multi-Agent (có Tool + RAG + Risk Check) vs Single-Agent (chatbot đơn)")
    compare_input = st.text_input(
        "Nhập câu hỏi để so sánh",
        value="Khách hàng KH001 muốn vay 2 tỷ mua nhà, thu nhập 45 triệu/tháng, đang có khoản vay ô tô 800 triệu. Có duyệt được không, cần thủ tục gì?",
    )

    if st.button("Chạy so sánh"):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 🤖 Single-Agent (Baseline)")
            with st.spinner("Đang xử lý..."):
                t0 = time.time()
                single_result = run_single_agent_baseline(compare_input)
                t1 = time.time()
            st.write(single_result)
            st.caption(f"⏱️ {t1 - t0:.1f} giây | Không tool · Không RAG · Không risk check")

        with col2:
            st.markdown("### 🏦 Multi-Agent (SHB Digital Expert Agents)")
            with st.spinner("Đang phối hợp cùng đội ngũ chuyên gia..."):
                t0 = time.time()
                multi_result = run_orchestrator(compare_input)
                t1 = time.time()
            st.write(multi_result)
            st.caption(f"⏱️ {t1 - t0:.1f} giây | Có tool thật · Có tra cứu quy định · Có cảnh báo rủi ro")

        st.divider()
        st.markdown("""
        **Nhận xét khách quan:** Multi-Agent chậm hơn Single-Agent (do gọi nhiều lượt model + tool),
        nhưng đổi lại có: căn cứ số liệu thật (CIC, DTI tính toán), trích dẫn quy định nội bộ,
        cảnh báo rủi ro tự động, và truy vết được quyết định — quan trọng hơn tốc độ trong bối cảnh
        nghiệp vụ ngân hàng, nơi 1 quyết định sai có chi phí cao hơn nhiều so với vài giây chờ đợi.
        """)
with tab_dashboard:
    st.subheader("📊 Agent Trace Dashboard — Nhật ký xử lý gần nhất")
    log = orchestrator_module.LAST_RUN_LOG
    if not log["user_input"]:
        st.info("Chưa có câu hỏi nào được xử lý. Hãy đặt câu hỏi ở tab Chat trước.")
    else:
        st.markdown(f"**Yêu cầu:** {log['user_input']}")
        col1, col2, col3 = st.columns(3)
        col1.metric("Số Expert được gọi", len(log["experts_called"]))
        col2.metric("Số lượt gọi Tool", len(log["tool_calls"]))
        col3.metric("Cảnh báo rủi ro", "Có ⚠️" if log["risk_flagged"] else "Không")
        st.divider()
        st.markdown("### 🔀 Collaboration Flow")
        flow_text = "**Planner (Fast Routing)** → "
        flow_text += " + ".join([f"**{e.capitalize()} Expert**" for e in log["experts_called"]])
        if log["synthesis_used"]:
            flow_text += " → **Synthesis Agent** → Kết quả cuối"
        else:
            flow_text += " → Kết quả cuối (bỏ qua Synthesis vì chỉ 1 Expert)"
        st.markdown(flow_text)

        st.divider()
        st.markdown("### 🧠 Case Memory — State hiện tại")
        mem = log.get("memory_state", {})
        if mem:
            c1, c2, c3 = st.columns(3)
            c1.metric("Hồ sơ đang xử lý", mem.get("customer_id", "—"))
            c2.metric("Dữ liệu đã cache", mem.get("cached_tools", 0))
            c3.metric("Lượt trao đổi", mem.get("history_length", 0))
            if mem.get("facts"):
                st.markdown("**Dữ kiện đã xác lập trong phiên:**")
                for k, v in mem["facts"].items():
                    label = {"loan_amount": "Số tiền vay", "income_monthly": "Thu nhập/tháng"}.get(k, k)
                    st.markdown(f"- {label}: `{v:,} VNĐ`")
            if mem.get("experts_consulted"):
                st.markdown(f"**Chuyên gia đã tham gia case:** {', '.join(e.capitalize() for e in mem['experts_consulted'])}")

        st.divider()
        st.markdown("### 🔧 Task Status — Tool Calls")
        if log["tool_calls"]:
            for call in log["tool_calls"]:
                st.markdown(f"- **{call['expert'].capitalize()} Expert** gọi `{call['tool']}({call['args']})` → `{call['result']}`")
        else:
            st.markdown("_Không có tool nào được gọi cho yêu cầu này._")

        st.divider()
        st.markdown("### ⏱️ Timing Breakdown")
        t = log["timings"]
        st.markdown(f"""
        - Routing (chọn Expert): **{t['routing_sec']}s**
        - Gọi Expert song song (+ tool): **{t['experts_sec']}s**
        - Synthesis (tổng hợp): **{t['synthesis_sec']}s**
        - **Tổng thời gian: {t['total_sec']}s**
        """)