import re
from dataclasses import dataclass


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]


# Identifier keys whose literal values must appear in the same line as the citation.
_SPOT_CHECK_KEYS = {
    "shipment.pod_id",
    "shipment.tracking_id",
    "shipment.receiver",
    "order.id",
}

# Lines matching these patterns are structural (salutation, sign-off, Re: header)
# and legitimately carry no citation.
_STRUCTURAL_RE = re.compile(
    r'^(Re:|Dear |To Whom|Sincerely|Best regards|Yours |The Merchant|\[Merchant)',
    re.IGNORECASE,
)


def validate_citations(draft: str, bundle: dict) -> ValidationResult:
    """Validate [source: key, ...] citations in every substantive line.

    Rules:
    - Every non-empty, non-structural line must have a [source: ...] tag.
    - Every cited key must exist in the bundle.
    - For identifier keys (pod_id, tracking_id, receiver, order.id), the
      literal value must appear somewhere on the same line.

    Uses line-based splitting rather than sentence-splitting because the
    citation tag contains dots (e.g. order.id) that break naive sentence
    splitters, and because Gemini writes one cited claim per line.
    """
    errors = []

    lines = draft.strip().splitlines()

    sentence_n = 0
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # pure markdown bold section header: **Some Header** or **Some Header:**
        # detected before stripping so we catch headers without trailing colons
        if re.match(r'^\*\*[^*]+\*\*$', line) and '[source:' not in line:
            continue

        # strip bold/italic markers for content analysis
        clean = re.sub(r'\*+', '', line).strip()
        if not clean or clean.startswith('#'):
            continue

        # section headers: short lines ending with ':' (with or without bold)
        if clean.endswith(':') and '[source:' not in clean:
            continue

        # salutations, sign-offs, document titles
        if _STRUCTURAL_RE.match(clean):
            continue

        has_citation = re.search(r'\[source:\s*([^\]]+)\]', clean)

        sentence_n += 1

        if not has_citation:
            errors.append(f"line {sentence_n} missing citation: {clean[:70]}...")
            continue

        cited_keys = [k.strip() for k in has_citation.group(1).split(',')]

        for key in cited_keys:
            if key not in bundle:
                errors.append(f"line {sentence_n} cites unknown key '{key}'")

        for key in cited_keys:
            if key in _SPOT_CHECK_KEYS and key in bundle:
                value = str(bundle[key])
                if value and value not in clean:
                    errors.append(f"line {sentence_n} cites '{key}' but value '{value}' not in text")

    return ValidationResult(valid=len(errors) == 0, errors=errors)
