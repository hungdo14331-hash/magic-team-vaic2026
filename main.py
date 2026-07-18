# main.py
import streamlit as st
import time
from agents.orchestrator import run_orchestrator, run_single_agent_baseline

st.set_page_config(page_title="SHB Digital Expert Agents", page_icon="🏦", layout="wide")

st.title("🏦 SHB Digital Expert Agents")
st.caption("Hội đồng chuyên gia số cho Nghiệp vụ Ngân hàng — VAIC 2026")

tab_chat, tab_compare = st.tabs(["💬 Chat với Đội ngũ Expert", "⚖️ So sánh Multi-Agent vs Single-Agent"])

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