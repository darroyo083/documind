import json
import re
from datetime import date

import httpx

from app.domain.analysis import (
    AnalysisSource,
    DocumentAnalysisContext,
    ProviderDocumentAnalysis,
    ProviderImportantDate,
    ProviderKeyFact,
)
from app.domain.errors import ProviderError

_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_ABBREVIATIONS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_exact_date(expression: str) -> str | None:
    """Parse an exact calendar date into ISO ``YYYY-MM-DD`` or return None.

    Only unambiguous full dates are accepted. Partial dates (a month and year
    without a day) and ambiguous numeric dates return ``None`` so that missing
    components are never invented.
    """
    text = expression.strip()

    month_pattern = (
        r"january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|"
        r"august|aug|september|sep|sept|october|oct|november|nov|december|dec"
    )

    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if iso:
        return _parse_date(text, int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    named_day_first = re.search(
        rf"\b(\d{{1,2}})\s+({month_pattern})\b(?:\.)?\s*,?\s*(\d{{4}})\b",
        text,
        re.IGNORECASE,
    )
    if named_day_first:
        month = _resolve_month(named_day_first.group(2))
        return _parse_date(
            text, int(named_day_first.group(3)), month, int(named_day_first.group(1))
        )

    named_month_first = re.search(
        rf"\b({month_pattern})\s+(\d{{1,2}})\b(?:st|nd|rd|th)?\.?,?\s*(\d{{4}})\b",
        text,
        re.IGNORECASE,
    )
    if named_month_first:
        month = _resolve_month(named_month_first.group(1))
        return _parse_date(
            text, int(named_month_first.group(3)), month, int(named_month_first.group(2))
        )

    numeric = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if numeric:
        first = int(numeric.group(1))
        second = int(numeric.group(2))
        year = int(numeric.group(3))
        if first > 12 >= second:
            return _parse_date(text, year, second, first)
        if second > 12 >= first:
            return _parse_date(text, year, first, second)
        if first <= 12 and second <= 12:
            return None
    return None


def _parse_date(expression: str, year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _resolve_month(name: str) -> int:
    lowered = name.lower()
    return _MONTH_NAMES.get(lowered) or _MONTH_ABBREVIATIONS.get(lowered) or 0


def important_date_normalized(value: str, provider_suggested: object) -> str | None:
    """Validate an important-date's normalized representation.

    Server owns date normalization. It derives the date from the visible value.
    A provider-supplied date is accepted only when it exactly matches the
    derived date. A claimed date without a supported exact expression in the
    value is discarded (partial/ambiguous dates stay null). A direct contradiction
    or a malformed provider date raises ``ValueError``.
    """
    derived = parse_exact_date(value)
    if provider_suggested is None:
        return derived
    if not isinstance(provider_suggested, str):
        raise ValueError("Normalized date must be an ISO string or null")
    normalized = provider_suggested.strip()
    if not normalized:
        return derived
    parsed = (
        _parse_date(normalized, *_extract_parts(normalized)) if _looks_iso(normalized) else None
    )
    if parsed is None:
        raise ValueError("Normalized date is not a valid ISO date")
    if derived is None:
        return None
    if derived != parsed:
        raise ValueError("Normalized date contradicts the source text")
    return derived


def _looks_iso(text: str) -> bool:
    return re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) is not None


def _extract_parts(text: str) -> tuple[int, int, int]:
    year, month, day = (int(part) for part in text.split("-"))
    return year, month, day


class DeterministicAnalysisProvider:
    """Deterministic, keyword-driven mock for tests and local development.

    It is NOT an intelligent classifier. It returns predictable structure from
    known Fixture phrasing so the full pipeline can run offline. The documentation
    marks it as mock structured analysis, not real AI extraction.
    """

    _TYPE_KEYWORDS: list[tuple[str, str]] = [
        ("insurance policy", "insurance_policy"),
        ("insurance", "insurance_policy"),
        ("policy", "insurance_policy"),
        ("coverage", "insurance_policy"),
        ("contract", "contract"),
        ("agreement", "contract"),
        ("termination notice", "contract"),
        ("invoice", "invoice"),
        ("statement", "bank_statement"),
        ("tax", "tax_document"),
        ("employment", "employment_document"),
        ("salary", "employment_document"),
        ("housing", "housing_document"),
        ("rental", "housing_document"),
        ("pension", "pension_document"),
        ("letter", "official_letter"),
        ("receipt", "receipt"),
        ("report", "report"),
    ]

    @property
    def model_name(self) -> str:
        return "deterministic-analysis"

    async def analyze(self, context: DocumentAnalysisContext) -> ProviderDocumentAnalysis:
        combined = context.render()
        document_type = self._detect_type(combined)
        normalized_title = self._detect_title(context.sources)
        summary = self._detect_summary(context.sources)
        important_dates = self._detect_dates(context.sources)
        key_facts = self._detect_facts(combined, context.sources)
        return ProviderDocumentAnalysis(
            document_type=document_type,
            normalized_title=normalized_title,
            summary=summary,
            important_dates=important_dates,
            key_facts=key_facts,
        )

    @classmethod
    def _detect_type(cls, text: str) -> str:
        lowered = text.lower()
        for keyword, document_type in cls._TYPE_KEYWORDS:
            if keyword in lowered:
                return document_type
        return "unknown"

    @classmethod
    def _detect_title(cls, sources: list[AnalysisSource]) -> str:
        for source in sources:
            for line in source.content.splitlines():
                stripped = line.strip().strip("*#")
                if stripped:
                    return stripped[:120]
        return "Untitled document"

    @classmethod
    def _detect_summary(cls, sources: list[AnalysisSource]) -> str:
        for source in sources:
            for line in source.content.splitlines():
                stripped = line.strip().strip("*#")
                if len(stripped) >= 40:
                    return stripped[:500]
        return ""

    @classmethod
    def _detect_dates(cls, sources: list[AnalysisSource]) -> list[ProviderImportantDate]:
        patterns = [
            (
                "Expiration date",
                re.compile(r"expir(?:es|ation)[^\n]*?(\d{1,2}\s+\w+\s+\d{4})", re.IGNORECASE),
            ),
            (
                "Effective date",
                re.compile(r"effective[^\n]*?(\d{1,2}\s+\w+\s+\d{4})", re.IGNORECASE),
            ),
            (
                "Document date",
                re.compile(r"dated?\s+(\d{1,2}\s+\w+\s+\d{4})", re.IGNORECASE),
            ),
        ]
        result: list[ProviderImportantDate] = []
        seen: set[str] = set()
        for source in sources:
            for label, pattern in patterns:
                for match in pattern.finditer(source.content):
                    expression = match.group(1)
                    if expression in seen:
                        continue
                    seen.add(expression)
                    result.append(
                        ProviderImportantDate(
                            label=label,
                            value=expression,
                            normalized_date=parse_exact_date(expression),
                            source_ids=[source.source_id],
                        )
                    )
                    break
        return result

    @classmethod
    def _detect_facts(cls, combined: str, sources: list[AnalysisSource]) -> list[ProviderKeyFact]:
        patterns = [
            ("Cancellation notice", re.compile(r"cancellation\D{0,60}?(\d+\s+\w+)", re.IGNORECASE)),
            (
                "Termination notice",
                re.compile(r"termination\D{0,60}?(\d+\s+(?:days?|months?|weeks?))", re.IGNORECASE),
            ),
            ("Coverage", re.compile(r"coverage\D{0,30}?([^\n]{5,60})", re.IGNORECASE)),
            (
                "Amount",
                re.compile(r"(?:amount|limit|value)\D{0,30}?(\$[0-9][0-9,.]*)", re.IGNORECASE),
            ),
        ]
        result: list[ProviderKeyFact] = []
        for label, pattern in patterns:
            for source in sources:
                match = pattern.search(source.content)
                if match:
                    result.append(
                        ProviderKeyFact(
                            label=label, value=match.group(1).strip(), source_ids=[source.source_id]
                        )
                    )
                    break
        return result


class DeepSeekDocumentAnalysisProvider:
    """Production structured-analysis adapter reusing DeepSeek chat completions."""

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

    async def analyze(self, context: DocumentAnalysisContext) -> ProviderDocumentAnalysis:
        system_prompt = (
            "Return exactly one valid JSON object with exactly these five keys: "
            '"document_type", "normalized_title", "summary", "important_dates", '
            '"key_facts". '
            "document_type must be exactly one of contract, invoice, insurance_policy, "
            "bank_statement, tax_document, employment_document, housing_document, "
            "pension_document, official_letter, receipt, report, other, unknown; "
            "use other when no exact type matches. "
            "normalized_title and summary must be strings; use an empty string when "
            "unavailable. important_dates and key_facts must be arrays; use [] when "
            "none. "
            'Each important_dates item must have "label", "value", "normalized_date", '
            '"source_ids". normalized_date must be ISO YYYY-MM-DD only for a full, '
            "exact date; otherwise use null. Each key_facts item must have "
            '"label", "value", "source_ids". '
            "Use only SOURCE IDs present in the supplied text. Every date and fact "
            "must cite at least one source containing its evidence. Do not use "
            "external knowledge or invent labels, values, dates, or citations. "
            "normalized_title must be the document title as written. Keep summary "
            "to one concise sentence. Do not add prose or extra keys."
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
            raise ProviderError("Document analysis provider failed") from exc

    def _parse(self, parsed: object) -> ProviderDocumentAnalysis:
        if not isinstance(parsed, dict):
            raise ProviderError("Document analysis provider returned an invalid structure")
        document_type = parsed.get("document_type")
        normalized_title = parsed.get("normalized_title")
        summary = parsed.get("summary")
        if not isinstance(document_type, str):
            raise ProviderError("Document analysis provider returned invalid metadata")
        if normalized_title is None:
            normalized_title = ""
        if not isinstance(normalized_title, str):
            raise ProviderError("Document analysis provider returned invalid metadata")
        if not isinstance(summary, str):
            summary = ""
        important_dates = self._parse_dates(parsed.get("important_dates"))
        key_facts = self._parse_facts(parsed.get("key_facts"))
        return ProviderDocumentAnalysis(
            document_type=document_type,
            normalized_title=normalized_title,
            summary=summary,
            important_dates=important_dates,
            key_facts=key_facts,
        )

    def _parse_dates(self, raw: object) -> list[ProviderImportantDate]:
        if not isinstance(raw, list):
            raise ProviderError("Document analysis provider returned invalid important_dates")
        result: list[ProviderImportantDate] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ProviderError("Document analysis provider returned an invalid date entry")
            label = item.get("label")
            value = item.get("value")
            normalized_date = item.get("normalized_date")
            source_ids = item.get("source_ids")
            if not isinstance(label, str) or not isinstance(value, str):
                raise ProviderError("Document analysis provider returned invalid date values")
            if normalized_date is not None and not isinstance(normalized_date, str):
                raise ProviderError(
                    "Document analysis provider returned an invalid normalized date"
                )
            if not isinstance(source_ids, list) or not all(
                isinstance(source_id, str) for source_id in source_ids
            ):
                raise ProviderError("Document analysis provider returned invalid date sources")
            result.append(
                ProviderImportantDate(
                    label=label,
                    value=value,
                    normalized_date=normalized_date,
                    source_ids=list(source_ids),
                )
            )
        return result

    def _parse_facts(self, raw: object) -> list[ProviderKeyFact]:
        if not isinstance(raw, list):
            raise ProviderError("DeepSeek provider returned invalid key_facts")
        result: list[ProviderKeyFact] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ProviderError("DeepSeek provider returned an invalid fact entry")
            label = item.get("label")
            value = item.get("value")
            source_ids = item.get("source_ids")
            if not isinstance(label, str) or not isinstance(value, str):
                raise ProviderError("DeepSeek provider returned invalid fact values")
            if not isinstance(source_ids, list) or not all(
                isinstance(source_id, str) for source_id in source_ids
            ):
                raise ProviderError("DeepSeek provider returned invalid fact sources")
            result.append(
                ProviderKeyFact(
                    label=label,
                    value=value,
                    source_ids=list(source_ids),
                )
            )
        return result
