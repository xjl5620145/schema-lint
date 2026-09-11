"""Schema.org / JSON-LD extraction and validation.

Pure standard library on purpose: no Apify SDK, no HTTP client, no third-party
deps. That keeps this module unit-testable on its own and keeps the Docker image
small.

    python3 -c "from validator import lint_html; print(lint_html(open('x.html').read()))"
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

JSONLD_PATTERN = re.compile(
    r"<script\b[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?([+-]\d{2}:?\d{2}|Z)?)?$")
PRICE = re.compile(r"^\d+(\.\d+)?$")

# Fields Google requires for a rich result to be eligible at all.
REQUIRED: dict[str, list[str]] = {
    "Product": ["name", "image", "offers"],
    "Article": ["headline", "datePublished", "author"],
    "NewsArticle": ["headline", "datePublished", "author"],
    "BlogPosting": ["headline", "datePublished", "author"],
    "LocalBusiness": ["name", "address"],
    "Organization": ["name", "url"],
    "WebSite": ["name", "url"],
    "BreadcrumbList": ["itemListElement"],
    "FAQPage": ["mainEntity"],
    "HowTo": ["name", "step"],
    "Event": ["name", "startDate", "location"],
    "JobPosting": ["title", "description", "datePosted", "hiringOrganization"],
    "Recipe": ["name", "image"],
    "Review": ["itemReviewed", "reviewRating", "author"],
    "VideoObject": ["name", "thumbnailUrl", "uploadDate"],
    "Person": ["name"],
}

# Fields that don't block eligibility but measurably hurt it.
RECOMMENDED: dict[str, list[str]] = {
    "Product": ["brand", "sku", "aggregateRating", "description"],
    "Article": ["image", "publisher", "dateModified"],
    "NewsArticle": ["image", "publisher", "dateModified"],
    "BlogPosting": ["image", "publisher", "dateModified"],
    "Organization": ["logo", "sameAs"],
    "WebSite": ["potentialAction", "publisher"],
    "LocalBusiness": ["telephone", "openingHours", "geo"],
    "Event": ["endDate", "offers", "image"],
    "Recipe": ["recipeIngredient", "recipeInstructions", "author"],
    "JobPosting": ["validThrough", "employmentType", "jobLocation"],
}

DATE_FIELDS = {"datePublished", "dateModified", "datePosted", "startDate", "endDate", "uploadDate", "validThrough"}
URL_FIELDS = {"url", "image", "logo", "thumbnailUrl", "contentUrl", "sameAs"}


def iter_typed_nodes(node: Any) -> Iterator[dict]:
    """Yield every dict that carries an @type, including nodes nested in @graph."""
    if isinstance(node, dict):
        if node.get("@type"):
            yield node
        for value in node.values():
            yield from iter_typed_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_typed_nodes(value)


def type_names(node: dict) -> list[str]:
    raw = node.get("@type")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _has(node: dict, field: str) -> bool:
    value = node.get(field)
    return value is not None and value != "" and value != [] and value != {}


def _issue(severity: str, schema_type: str, field: str, message: str, fix: str) -> dict:
    return {
        "severity": severity,
        "type": schema_type,
        "field": field,
        "message": message,
        "recommendation": fix,
    }


def _check_product(node: dict, issues: list[dict]) -> None:
    """Product.offers is where most real-world breakage lives."""
    offers = node.get("offers")
    if not _has(node, "offers"):
        return
    offer = offers[0] if isinstance(offers, list) and offers else offers
    if not isinstance(offer, dict):
        issues.append(
            _issue("error", "Product", "offers", "offers is not an object", "Use an Offer object or an array of them")
        )
        return
    for field in ("price", "priceCurrency"):
        if not _has(offer, field):
            issues.append(
                _issue(
                    "error",
                    "Product",
                    f"offers.{field}",
                    f"Offer is missing '{field}'",
                    f"Add offers.{field} - Google will not render a price without it",
                )
            )
    price = offer.get("price")
    if price is not None and not PRICE.match(str(price).strip()):
        issues.append(
            _issue(
                "error",
                "Product",
                "offers.price",
                f"price '{price}' is not a plain number",
                "Use a bare number like 29.99, no currency symbol, no comma separator",
            )
        )
    if not _has(offer, "availability"):
        issues.append(
            _issue(
                "warning",
                "Product",
                "offers.availability",
                "Offer has no availability",
                "Add availability such as https://schema.org/InStock",
            )
        )


def _check_formats(node: dict, schema_type: str, issues: list[dict]) -> None:
    for field in DATE_FIELDS:
        value = node.get(field)
        if isinstance(value, str) and not ISO_DATE.match(value.strip()):
            issues.append(
                _issue(
                    "warning",
                    schema_type,
                    field,
                    f"'{value}' is not ISO 8601",
                    "Use YYYY-MM-DD or a full ISO 8601 timestamp with timezone",
                )
            )
    for field in URL_FIELDS:
        value = node.get(field)
        if isinstance(value, str) and value.strip() and not value.strip().lower().startswith(("http://", "https://")):
            issues.append(
                _issue(
                    "warning",
                    schema_type,
                    field,
                    f"'{value}' is not an absolute URL",
                    "Use a fully qualified https:// URL",
                )
            )


def validate_node(node: dict) -> list[dict]:
    issues: list[dict] = []
    for schema_type in type_names(node):
        for field in REQUIRED.get(schema_type, []):
            if not _has(node, field):
                issues.append(
                    _issue(
                        "error",
                        schema_type,
                        field,
                        f"Missing required field '{field}'",
                        f"Add '{field}' - required for {schema_type} to be eligible for rich results",
                    )
                )
        for field in RECOMMENDED.get(schema_type, []):
            if not _has(node, field):
                issues.append(
                    _issue(
                        "warning",
                        schema_type,
                        field,
                        f"Missing recommended field '{field}'",
                        f"Add '{field}' to improve how {schema_type} renders",
                    )
                )
        _check_formats(node, schema_type, issues)
        if schema_type == "Product":
            _check_product(node, issues)
    return issues


def extract_blocks(html: str) -> tuple[list[Any], list[dict]]:
    """Return (parsed blocks, parse errors)."""
    blocks: list[Any] = []
    errors: list[dict] = []
    for index, raw in enumerate(JSONLD_PATTERN.findall(html or "")):
        text = raw.strip()
        if not text:
            continue
        try:
            blocks.append(json.loads(text))
        except json.JSONDecodeError as exc:
            errors.append(
                _issue(
                    "error",
                    "-",
                    f"block[{index}]",
                    f"Invalid JSON: {exc.msg} at line {exc.lineno}",
                    "Validate the block at https://validator.schema.org before publishing",
                )
            )
    return blocks, errors


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def lint_html(html: str) -> dict:
    """Lint one page's HTML. Returns a flat, dataset-ready dict."""
    blocks, parse_errors = extract_blocks(html)

    if not blocks:
        return {
            "jsonLdBlockCount": 0,
            "types": [],
            "issues": parse_errors
            + [
                _issue(
                    "error",
                    "-",
                    "json-ld",
                    "No JSON-LD structured data found on this page",
                    "Add a JSON-LD block - this page cannot produce a rich result at all",
                )
            ],
            "errorCount": 1 + len(parse_errors),
            "warningCount": 0,
            "score": 0,
            "grade": "F",
        }

    issues: list[dict] = list(parse_errors)
    types: list[str] = []
    for block in blocks:
        for node in iter_typed_nodes(block):
            for name in type_names(node):
                if name not in types:
                    types.append(name)
            issues.extend(validate_node(node))

    error_count = sum(1 for i in issues if i["severity"] == "error")
    warning_count = sum(1 for i in issues if i["severity"] == "warning")
    score = max(0, 100 - error_count * 15 - warning_count * 5)

    return {
        "jsonLdBlockCount": len(blocks),
        "types": types,
        "issues": issues,
        "errorCount": error_count,
        "warningCount": warning_count,
        "score": score,
        "grade": _grade(score),
    }
