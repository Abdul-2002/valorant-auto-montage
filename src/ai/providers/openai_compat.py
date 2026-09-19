from __future__ import annotations

from dataclasses import dataclass

import httpx

from src.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from src.ai.providers.base import BriefContext, BriefProvider
from src.ai.schema import CreativeBrief


@dataclass
class OpenAICompatibleBriefProvider(BriefProvider):
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.7
    timeout_sec: float = 30.0

    def generate_brief(self, ctx: BriefContext) -> CreativeBrief | None:
        if not self.base_url or not self.model:
            return None

        user_prompt = build_user_prompt(
            enriched_events=ctx.enriched_events,
            creative_config=ctx.creative_config_resolved,
            beat_map=ctx.beat_map,
        )

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = {
            "model": self.model,
            "temperature": float(self.temperature),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                r = client.post(f"{self.base_url.rstrip('/')}/chat/completions", headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
        except Exception:
            return None

        try:
            content = data["choices"][0]["message"]["content"]
            return CreativeBrief.model_validate_json(content)
        except Exception:
            return None
