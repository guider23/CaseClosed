import json
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential, wait_fixed, wait_random
from google import genai
from google.genai import types as genai_types
from anthropic import Anthropic
from openai import OpenAI

from .config import config
from .db import Dispute


@dataclass
class DraftResponse:
    text: str
    model: str
    attempt: int


SYSTEM_PROMPT = """You are drafting a formal chargeback rebuttal for a payment dispute.

CRITICAL RULES:
1. Use ONLY facts present in the evidence bundle JSON provided
2. EVERY sentence must end with [source: key1, key2, ...] citing the bundle keys used
3. Structure: brief intro, delivery evidence section, customer behavior section, conclusion requesting reversal
4. If a needed fact is missing from the bundle, omit that point entirely - NEVER speculate or infer
5. Never mention the customer in abusive terms
6. Professional, factual tone throughout

If the evidence bundle is insufficient to make a case, state that clearly rather than improvising."""


class Composer:
    def compose(self, bundle: dict, dispute: Dispute) -> DraftResponse:
        raise NotImplementedError


class LLMComposer(Composer):
    def __init__(self):
        self.provider = config.llm_provider
        self.model = config.llm_model
        self.timeout = config.llm_timeout_seconds

        if self.provider == "gemini":
            self.client = genai.Client(api_key=config.llm_api_key)
        elif self.provider == "anthropic":
            self.client = Anthropic(api_key=config.llm_api_key, timeout=self.timeout)
        elif self.provider == "openai":
            self.client = OpenAI(api_key=config.llm_api_key, timeout=self.timeout)
        else:
            raise ValueError(f"unknown provider: {self.provider}")

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(60) + wait_random(0, 20))
    def compose(self, bundle: dict, dispute: Dispute, validation_feedback: str | None = None) -> DraftResponse:
        prompt = self._build_prompt(bundle, dispute, validation_feedback)

        if self.provider == "gemini":
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0
                )
            )
            try:
                text = response.text
            except AttributeError:
                text = response.candidates[0].content.parts[0].text
        elif self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text
        elif self.provider == "openai":
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ]
            )
            text = response.choices[0].message.content

        return DraftResponse(text=text, model=self.model, attempt=1)

    def _build_prompt(self, bundle: dict, dispute: Dispute, validation_feedback: str | None) -> str:
        lines = [
            f"Draft a chargeback rebuttal for dispute {dispute.dispute_id}.",
            f"Dispute type: {dispute.dispute_type}",
            f"Reason: {dispute.reason_code}",
            f"Amount: {dispute.amount} {dispute.currency}",
            "",
            "Evidence bundle (JSON):",
            json.dumps(bundle, indent=2)
        ]

        if validation_feedback:
            lines.extend([
                "",
                "PREVIOUS ATTEMPT FAILED VALIDATION:",
                validation_feedback,
                "",
                "Fix the issues above and regenerate the rebuttal."
            ])

        return "\n".join(lines)
