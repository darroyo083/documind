import json
import re

import httpx

from app.domain.actions import (
    DocumentActionContext,
    ProviderAction,
    ProviderDocumentActions,
)
from app.domain.errors import ProviderError
from app.infrastructure.analysis_providers import parse_exact_date


class DeterministicActionProvider:
    """Deterministic, phrase-driven mock for tests and local development.

    It is NOT real AI extraction. It detects predictable fixture phrasing so the
    full pipeline can run offline. Documentation marks it as deterministic
    development behavior, not production intelligence.
    """

    @property
    def model_name(self) -> str:
        return "deterministic-actions"

    async def generate_actions(self, context: DocumentActionContext) -> ProviderDocumentActions:
        actions: list[ProviderAction] = []
        for source in context.sources:
            actions.extend(self._extract_from_source(source))
        return ProviderDocumentActions(actions=actions)

    @classmethod
    def _extract_from_source(cls, source) -> list[ProviderAction]:
        text = source.content
        source_id = source.source_id
        actions: list[ProviderAction] = []

        def add(action_type: str, item_title: str, timing: str | None, due: str | None) -> None:
            actions.append(
                ProviderAction(
                    action_type=action_type,
                    title=item_title,
                    description=None,
                    timing_text=timing,
                    due_date=due,
                    source_ids=[source_id],
                )
            )

        match = re.search(
            r"cancellation requires written notice(?:\s+at least\s+(\d+\s+\w+))?",
            text,
            re.IGNORECASE,
        )
        if match:
            timing = (
                f"At least {match.group(1)} before cancellation"
                if match.group(1)
                else "Before cancellation"
            )
            add("required_action", "Send written cancellation notice", timing, None)

        match = re.search(r"payment is due by\s+(\d{1,2}\s+\w+\s+\d{4})", text, re.IGNORECASE)
        if match:
            add("deadline", "Pay the invoice", match.group(1), parse_exact_date(match.group(1)))

        match = re.search(r"renews automatically on\s+(\d{1,2}\s+\w+\s+\d{4})", text, re.IGNORECASE)
        if match:
            add(
                "reminder",
                "Policy renewal date",
                f"Renews automatically on {match.group(1)}",
                None,
            )

        match = re.search(
            r"we recommend\s+(?:reviewing|updating|checking|verifying|confirming)?"
            r"\s*(?:your\s+|the\s+|a\s+|an\s+)?(.+)",
            text,
            re.IGNORECASE,
        )
        if match:
            phrase = match.group(1).strip().rstrip(".")
            add(
                "recommended_action",
                f"Review {phrase}" if phrase else "Review recommended item",
                None,
                None,
            )

        match = re.search(r"must submit\s+(.+)", text, re.IGNORECASE)
        if match:
            add(
                "required_action",
                "Submit the form",
                f"Submit {match.group(1).strip().rstrip('.')}",
                None,
            )

        return actions


class DeepSeekDocumentActionProvider:
    """Production action-extraction adapter reusing DeepSeek chat completions."""

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str,
        timeout_seconds: float,
    ):
        if not api_key:
            raise ProviderError("DeepSeek API key is not configured")
        self.api_key = api_key
        self._model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate_actions(self, context: DocumentActionContext) -> ProviderDocumentActions:
        system_prompt = (
            "You extract document-grounded action items from text-only content. "
            'Return ONLY JSON with key "actions", a list of objects with keys '
            '"action_type", "title", "description", "timing_text", "due_date", '
            '"source_ids". action_type is ONLY one of: required_action, deadline, '
            "reminder, recommended_action. required_action only for explicit "
            "obligations in the document. recommended_action ONLY when the document "
            "explicitly recommends the action. deadline only when the document "
            "provides an action with an explicit deadline. reminder may represent an "
            "explicit important event or date without implying an obligation. "
            "due_date is ISO YYYY-MM-DD ONLY when the document gives an exact "
            "calendar date for the action, otherwise null. Never invent date "
            "components. Do not calculate relative deadlines. Use ONLY the source "
            "IDs shown as SOURCE <id> lines; every action must list at least one "
            "source ID containing its evidence. Do not use external knowledge. Do "
            "not invent helpful recommendations. Avoid duplicate actions. Keep "
            "titles concise. Return valid JSON only."
        )
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context.render()},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 2000,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
            raw_content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(raw_content)
            return self._parse(parsed)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError("Document action provider failed") from exc

    def _parse(self, parsed: object) -> ProviderDocumentActions:
        if not isinstance(parsed, dict) or not isinstance(parsed.get("actions"), list):
            raise ProviderError("Document action provider returned an invalid structure")
        actions: list[ProviderAction] = []
        for item in parsed["actions"]:
            if not isinstance(item, dict):
                raise ProviderError("Document action provider returned an invalid action")
            action_type = item.get("action_type")
            title = item.get("title")
            description = item.get("description")
            timing_text = item.get("timing_text")
            due_date = item.get("due_date")
            source_ids = item.get("source_ids")
            if not isinstance(action_type, str) or not isinstance(title, str):
                raise ProviderError("Document action provider returned invalid action fields")
            if description is not None and not isinstance(description, str):
                raise ProviderError("Document action provider returned an invalid description")
            if timing_text is not None and not isinstance(timing_text, str):
                raise ProviderError("Document action provider returned an invalid timing_text")
            if due_date is not None and not isinstance(due_date, str):
                raise ProviderError("Document action provider returned an invalid due_date")
            if not isinstance(source_ids, list) or not all(
                isinstance(source_id, str) for source_id in source_ids
            ):
                raise ProviderError("Document action provider returned invalid action sources")
            actions.append(
                ProviderAction(
                    action_type=action_type,
                    title=title,
                    description=description,
                    timing_text=timing_text,
                    due_date=due_date,
                    source_ids=list(source_ids),
                )
            )
        return ProviderDocumentActions(actions=actions)
