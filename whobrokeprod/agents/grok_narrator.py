"""Optional Grok narrator. Off by default; never used by experiments or tests.

It only turns an already-computed deterministic verdict into a short postmortem paragraph for the demo.
It never decides attribution. Requires XAI_API_KEY (and optionally XAI_MODEL) in the environment.
"""
from __future__ import annotations

import json
import os
import urllib.request

API_URL = "https://api.x.ai/v1/chat/completions"


def narrate(verdict_text: str, timeout: float = 30.0) -> str | None:
    key = os.environ.get("XAI_API_KEY")
    if not key:
        return None
    body = {
        "model": os.environ.get("XAI_MODEL", "grok-4"),
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "Write a 4-sentence blameless postmortem summary. Use only the "
             "facts given. Do not add new causes, numbers, or events."},
            {"role": "user", "content": verdict_text},
        ],
    }
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["choices"][0]["message"]["content"]
