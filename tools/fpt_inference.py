# tools/fpt_inference.py
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

FPT_API_KEY = os.getenv("FPT_API_KEY")
FPT_BASE_URL = os.getenv("FPT_BASE_URL")
FPT_MODEL_NAME = os.getenv("FPT_MODEL_NAME")


def _clean_reasoning_leak(text: str) -> str:
    """Cắt bớt phần 'nháp tính toán' khi phải dùng reasoning_content thay vì content sạch."""
    if not text:
        return text

    noise_patterns = [
        r"Let me (?:calculate|recalculate|verify|check|be more precise)[^\n]*\n",
        r"Using log:[^\n]*\n",
        r"\d+\.\d+\^\d+[^\n]*\n",
        r"[A-Za-z]\s*=\s*[\d.,]+\s*\*[^\n]*\n",
        r"ln\([\d.]+\)[^\n]*\n",
        r"e\^[\d.]+[^\n]*\n",
    ]

    lines = text.split("\n")
    noise_line_indices = set()
    for index, line in enumerate(lines):
        for pattern in noise_patterns:
            if re.search(pattern, line + "\n"):
                noise_line_indices.add(index)
                break

    cutoff = 0
    consecutive_noise = 0
    for index in range(len(lines)):
        if index in noise_line_indices or lines[index].strip() == "":
            consecutive_noise += 1
            cutoff = index + 1
        else:
            if consecutive_noise > 0 and index + 2 < len(lines):
                non_noise_streak = all(
                    j not in noise_line_indices for j in range(index, min(index + 3, len(lines)))
                )
                if non_noise_streak:
                    break
            consecutive_noise = 0

    if cutoff > 5 and cutoff < len(lines):
        cleaned = "\n".join(lines[cutoff:]).strip()
        if len(cleaned) > 50:
            return cleaned

    return text.strip()


def call_fpt_model(system_prompt: str, user_message: str, temperature: float = 0.7, max_tokens: int = 4000) -> str:
    """Gọi FPT AI Inference API."""
    if not FPT_API_KEY or not FPT_BASE_URL or not FPT_MODEL_NAME:
        return "Lỗi: Thiếu FPT_API_KEY, FPT_BASE_URL hoặc FPT_MODEL_NAME trong .env"

    headers = {
        "Authorization": f"Bearer {FPT_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
        response = requests.post(FPT_BASE_URL, json=payload, headers=headers, timeout=90)
        response.raise_for_status()
        data = response.json()

        message = data["choices"][0]["message"]
        content = message.get("content")
        used_reasoning_fallback = False

        if not content:
            content = message.get("reasoning_content")
            used_reasoning_fallback = True

        if not content:
            return "Lỗi: Model không trả về nội dung (có thể do hết max_tokens)."

        if used_reasoning_fallback:
            content = _clean_reasoning_leak(content)

        return content.strip()
    except requests.exceptions.Timeout:
        return "Lỗi: FPT API timeout, thử lại."
    except requests.exceptions.HTTPError as e:
        return f"Lỗi HTTP từ FPT API: {response.status_code} - {response.text[:200]}"
    except Exception as e:
        return f"Lỗi gọi FPT API: {str(e)}"