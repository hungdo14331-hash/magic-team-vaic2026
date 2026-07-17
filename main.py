# main.py
import streamlit as st
import time
from agents.orchestrator import run_orchestrator

st.set_page_config(page_title="Magic Expert Agents", page_icon="🔮")

st.title("🔮 Magic Expert Agents")
st.caption("AI Co-Founder cho SME Việt Nam — VAIC 2026")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

user_input = st.chat_input("Nhập câu hỏi hoặc vấn đề của bạn...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Đang phân tích và hỏi ý kiến chuyên gia..."):
            start_time = time.time()
            response = run_orchestrator(user_input)
            elapsed = time.time() - start_time
        st.write(response)
        st.caption(f"⏱️ {elapsed:.1f} giây")

    st.session_state.messages.append({"role": "assistant", "content": response})