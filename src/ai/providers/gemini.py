from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from src.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from src.ai.providers.base import BriefContext, BriefProvider
from src.ai.schema import ClipCuration, CreativeBrief, EffectBiases, NarrativePhase, SpecialTreatment

logger = logging.getLogger(__name__)


class _GeminiArc(BaseModel):
    intro: NarrativePhase
    build: NarrativePhase
    climax: NarrativePhase
    outro: NarrativePhase


class _GeminiTreatment(BaseModel):
    """Per-kill directorial choice, constrained to the engine's recipe vocabulary."""

    event_idx: int = Field(ge=0)
    recipe: Literal["clean", "punch", "slow", "cinematic"]
    note: str = ""


class _GeminiBrief(BaseModel):
    """Rigid response schema for Gemini structured output.

    CreativeBrief allows dynamic dict keys and unions, which the Gemini schema
    converter cannot express; free-form JSON responses kept failing validation
    (wrong key names, dicts where lists were expected). This mirror model pins
    the exact shape so the API enforces it server-side.
    """

    narrative_arc: _GeminiArc
    clip_curation: ClipCuration
    effect_biases: EffectBiases
    transition_strategy: str = "beat_synced"
    treatments: list[_GeminiTreatment] = Field(default_factory=list)
    reasoning: str = ""
    intensity_bias: float = Field(ge=0.0, le=1.0, default=0.7)


def _to_creative_brief(g: _GeminiBrief) -> CreativeBrief:
    return CreativeBrief(
        narrative_arc={
            "intro": g.narrative_arc.intro,
            "build": g.narrative_arc.build,
            "climax": g.narrative_arc.climax,
            "outro": g.narrative_arc.outro,
        },
        clip_curation=g.clip_curation,
        effect_biases=g.effect_biases,
        transition_strategy=g.transition_strategy,
        special_treatments=[
            SpecialTreatment(event_idx=t.event_idx, note=t.note, treatment=t.recipe) for t in g.treatments
        ],
        reasoning=g.reasoning,
        intensity_bias=g.intensity_bias,
    )


@dataclass
class GeminiBriefProvider(BriefProvider):
    api_key: str
    model: str = "gemini-2.5-flash-lite"
    temperature: float = 0.7

    def _generate_with_fallback(self, client: object, user_prompt: str) -> object | None:
        """Call Gemini, retrying transient 5xx errors and falling back to a
        sibling model (lite <-> full sit in different capacity pools)."""
        from google.genai import errors as genai_errors  # type: ignore

        fallback = "gemini-2.5-flash" if "lite" in self.model else "gemini-2.5-flash-lite"
        attempts = [self.model, self.model, fallback]
        for i, model_name in enumerate(attempts):
            try:
                return client.models.generate_content(  # type: ignore[attr-defined]
                    model=model_name,
                    contents=[
                        {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_prompt}]},
                    ],
                    config={
                        "temperature": float(self.temperature),
                        "response_mime_type": "application/json",
                        "response_schema": _GeminiBrief,
                    },
                )
            except genai_errors.ServerError as e:
                logging.warning(
                    "Gemini %s unavailable (attempt %d/%d): %s", model_name, i + 1, len(attempts), e
                )
                time.sleep(2.0 * (i + 1))
        logging.error("Gemini brief failed: all models unavailable (%s)", ", ".join(attempts))
        return None

    def generate_brief(self, ctx: BriefContext) -> CreativeBrief | None:
        if not self.api_key:
            logging.warning("Gemini provider disabled (missing api_key)")
            return None

        # Lazy import so the project works without the dependency unless enabled.
        try:
            from google import genai  # type: ignore
        except Exception:
            logging.exception("Gemini provider unavailable: failed to import google-genai")
            return None

        client = genai.Client(api_key=self.api_key)

        user_prompt = build_user_prompt(
            enriched_events=ctx.enriched_events,
            creative_config=ctx.creative_config_resolved,
            beat_map=ctx.beat_map,
        )

        resp = self._generate_with_fallback(client, user_prompt)
        if resp is None:
            return None

        # Structured output: the SDK parses the response into _GeminiBrief.
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, _GeminiBrief):
            logging.warning("Gemini CreativeBrief (structured, model=%s): %s", self.model, parsed.reasoning)
            return _to_creative_brief(parsed)

        text = getattr(resp, "text", None)
        if not text:
            # Use root logger for visibility under Celery's default logging config.
            logging.warning("Gemini returned empty text (model=%s)", self.model)
            return None

        # Log the raw JSON (truncated) for debugging. Do NOT log api_key.
        log_preview = text if len(text) <= 4000 else (text[:4000] + "\n... (truncated)")
        # Use root logger for visibility under Celery's default logging config.
        logging.warning("Gemini CreativeBrief raw response (model=%s):\n%s", self.model, log_preview)

        try:
            return CreativeBrief.model_validate_json(text)
        except Exception as e:
            # Root logger so it's visible in container logs.
            logging.exception("Failed to parse Gemini CreativeBrief JSON: %s", e)
            return None
