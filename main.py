# main.py
import streamlit as st
import time
from agents.orchestrator import run_orchestrator

st.set_page_config(page_title="SHB Digital Expert Agents", page_icon="🏦")

st.title("🏦 SHB Digital Expert Agents")
st.caption("Hội đồng chuyên gia số cho Nghiệp vụ Ngân hàng — VAIC 2026")

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