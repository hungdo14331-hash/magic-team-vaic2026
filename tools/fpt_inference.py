# tools/fpt_inference.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

FPT_API_KEY = os.getenv("FPT_API_KEY")
FPT_BASE_URL = os.getenv("FPT_BASE_URL")
FPT_MODEL_NAME = os.getenv("FPT_MODEL_NAME")


def call_fpt_model(system_prompt: str, user_message: str, temperature: float = 0.7, max_tokens: int = 3000) -> str:
    """Gọi FPT AI Inference API."""
    if not FPT_API_KEY or not FPT_BASE_URL or not FPT_MODEL_NAME:
        return "Lỗi: Thiếu FPT_API_KEY, FPT_BASE_URL hoặc FPT_MODEL_NAME trong .env"

    headers = {
        "Authorization": f"Bearer {FPT_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": FPT_MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }
    try:
        response = requests.post(FPT_BASE_URL, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()

        message = data["choices"][0]["message"]
        content = message.get("content")

        # GLM-5.2 là model reasoning: đôi khi trả lời thật nằm trong reasoning_content
        if not content:
            content = message.get("reasoning_content")

        if not content:
            return "Lỗi: Model không trả về nội dung (có thể do hết max_tokens)."

        return content.strip()
    except requests.exceptions.Timeout:
        return "Lỗi: FPT API timeout, thử lại."
    except requests.exceptions.HTTPError as e:
        return f"Lỗi HTTP từ FPT API: {response.status_code} - {response.text[:200]}"
    except Exception as e:
        return f"Lỗi gọi FPT API: {str(e)}"