from __future__ import annotations

from dataclasses import dataclass

from src.ai.providers.base import BriefContext, BriefProvider
from src.ai.schema import CreativeBrief


@dataclass
class RuleOnlyBriefProvider(BriefProvider):
    def generate_brief(self, ctx: BriefContext) -> CreativeBrief | None:
        return None
