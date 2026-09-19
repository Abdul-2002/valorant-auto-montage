from __future__ import annotations

import os
import logging

from src.ai.providers.base import BriefContext, BriefProvider
from src.ai.providers.gemini import GeminiBriefProvider
from src.ai.providers.openai_compat import OpenAICompatibleBriefProvider
from src.ai.providers.rule_only import RuleOnlyBriefProvider
from src.config.models import AIDirectorConfig

logger = logging.getLogger(__name__)


def get_brief_provider(cfg: AIDirectorConfig) -> BriefProvider:
    if not cfg.enabled or cfg.provider == "rule_only":
        return RuleOnlyBriefProvider()
    if cfg.provider == "gemini":
        api_key = cfg.gemini.api_key or os.environ.get("GEMINI_API_KEY", "")
        return GeminiBriefProvider(api_key=api_key, model=cfg.gemini.model, temperature=cfg.gemini.temperature)
    if cfg.provider == "openai_compatible":
        api_key = cfg.openai_compatible.api_key or os.environ.get("OPENAI_API_KEY", "")
        base_url = cfg.openai_compatible.base_url or os.environ.get("OPENAI_BASE_URL", "")
        return OpenAICompatibleBriefProvider(
            base_url=base_url,
            api_key=api_key,
            model=cfg.openai_compatible.model,
            temperature=cfg.openai_compatible.temperature,
        )
    # Local is not implemented in v2 plan execution; fall back safely.
    return RuleOnlyBriefProvider()


def safe_generate_brief(*, cfg: AIDirectorConfig, ctx: BriefContext) -> object | None:
    try:
        return get_brief_provider(cfg).generate_brief(ctx)
    except Exception:
        logger.exception("Brief provider failed (provider=%s). Falling back to rule engine only.", cfg.provider)
        return None
