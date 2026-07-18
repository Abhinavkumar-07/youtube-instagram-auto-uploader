"""
Generates a YouTube title, description, tags, and Instagram caption for a
video using the Groq API (free tier, OpenAI-compatible, simple bearer auth).

Swap providers here if you want a different one -- nothing else in the
pipeline needs to change as long as generate_metadata() returns the same shape.
"""

import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = "llama-3.3-70b-versatile"  # strong, fast, free-tier friendly
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are a social media editor writing metadata for short-form \
podcast clip content targeting US/UK audiences, published on YouTube and \
Instagram Reels simultaneously. Given a source filename (and optional context), \
output ONLY valid JSON with this exact shape, no markdown fences, no preamble:

{"title": "...", "description": "...", "tags": ["...", "..."], "ig_caption": "..."}

Rules:
- title: under 70 characters, curiosity-driven but not misleading, for YouTube
- description: 2-4 sentences for YouTube, includes relevant keywords naturally, ends with 3-5 hashtags
- tags: 8-15 relevant single/short-phrase tags, no # symbol
- ig_caption: shorter and punchier than the YouTube description, 1-2 sentences, ends with 5-8 hashtags suited to Instagram Reels discovery
"""


def generate_metadata(filename: str, extra_context: str = "") -> dict:
    """Returns {"title": str, "description": str, "tags": list[str], "ig_caption": str}"""
    user_prompt = f"Filename: {filename}"
    if extra_context:
        user_prompt += f"\nContext: {extra_context}"

    body = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }

    response = requests.post(
        GROQ_URL,
        json=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
        },
    )
    if not response.ok:
        print("Groq API error response:")
        print(response.text)
    response.raise_for_status()

    raw = response.json()["choices"][0]["message"]["content"].strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    data = json.loads(raw)
    required = ("title", "description", "tags", "ig_caption")
    assert all(k in data for k in required)
    return data


if __name__ == "__main__":
    # quick manual test
    result = generate_metadata("ep12_clip_founder_burnout.mp4")
    print(json.dumps(result, indent=2))