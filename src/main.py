"""Apify Actor entrypoint: fetch each URL and lint its structured data.

Deliberately does NOT import the `apify` SDK. That SDK pulls in crawlee, which
conflicts with recent pydantic releases (`TypeError: cannot specify both default
and default_factory`) inside the apify/actor-python:3.13 image. We only need
three Apify features, and all three are one HTTP call each:

    read input    GET  /v2/key-value-stores/{storeId}/records/{inputKey}
    write output  POST /v2/datasets/{datasetId}/items
    log           just print() - Apify captures stdout
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validator import lint_html  # noqa: E402

API = "https://api.apify.com/v2"
USER_AGENT = (
    "Mozilla/5.0 (compatible; SchemaLint/0.1; +https://apify.com) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _auth() -> dict:
    token = os.environ.get("APIFY_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def get_input() -> dict:
    """Read the Actor input from the default key-value store."""
    store = os.environ.get("APIFY_DEFAULT_KEY_VALUE_STORE_ID")
    key = os.environ.get("APIFY_INPUT_KEY", "INPUT")
    if not store or not _auth():
        print("WARN: no key-value store or token in env, running with empty input")
        return {}
    url = f"{API}/key-value-stores/{store}/records/{key}"
    try:
        response = httpx.get(url, headers=_auth(), timeout=30)
    except httpx.HTTPError as exc:
        print(f"WARN: could not read input ({exc}), falling back to empty input")
        return {}
    if response.status_code != 200:
        print(f"WARN: input read returned HTTP {response.status_code}, using empty input")
        return {}
    body = response.json()
    return body if isinstance(body, dict) else {}


def push_data(items: list[dict]) -> None:
    """Write all results to the default dataset in one call."""
    dataset = os.environ.get("APIFY_DEFAULT_DATASET_ID")
    if not dataset or not _auth():
        print("WARN: no dataset id or token, cannot push results")
        return
    url = f"{API}/datasets/{dataset}/items"
    response = httpx.post(url, headers=_auth(), json=items, timeout=60)
    print(f"Pushed {len(items)} item(s) to dataset (HTTP {response.status_code})")


def set_status_message(message: str) -> None:
    run_id = os.environ.get("APIFY_ACTOR_RUN_ID")
    if not run_id or not _auth():
        return
    try:
        httpx.put(
            f"{API}/actor-runs/{run_id}",
            headers=_auth(),
            json={"statusMessage": message},
            timeout=30,
        )
    except httpx.HTTPError:
        pass


async def process(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    url: str,
    include_raw: bool,
) -> dict:
    result: dict = {
        "url": url,
        "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    async with semaphore:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            result.update(
                httpStatus=None,
                finalUrl=url,
                fetched=False,
                error=f"Request failed: {type(exc).__name__}: {exc}",
                score=0,
                grade="F",
            )
            return result

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower() and "text" not in content_type.lower():
        result.update(
            httpStatus=response.status_code,
            finalUrl=str(response.url),
            fetched=False,
            error=f"Not an HTML page (content-type: {content_type or 'unknown'})",
            score=0,
            grade="F",
        )
        return result

    report = lint_html(response.text)
    result.update(
        httpStatus=response.status_code,
        finalUrl=str(response.url),
        fetched=True,
        error=None,
        **report,
    )

    if include_raw:
        from validator import extract_blocks

        blocks, _ = extract_blocks(response.text)
        result["rawBlocks"] = blocks

    return result


async def main() -> None:
    actor_input = get_input() or {}
    urls = [u.strip() for u in (actor_input.get("urls") or []) if str(u).strip()]
    if not urls:
        raise ValueError("No URLs provided. Pass a non-empty 'urls' array.")

    max_concurrency = max(1, int(actor_input.get("maxConcurrency", 5)))
    timeout_ms = max(1000, int(actor_input.get("timeoutMs", 20000)))
    include_raw = bool(actor_input.get("includeRawBlocks", False))

    print(f"Checking structured data on {len(urls)} URL(s)")

    semaphore = asyncio.Semaphore(max_concurrency)
    limits = httpx.Limits(max_connections=max_concurrency, max_keepalive_connections=max_concurrency)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout_ms / 1000,
        limits=limits,
        headers={"user-agent": USER_AGENT, "accept": "text/html,application/xhtml+xml"},
    ) as client:
        results = await asyncio.gather(
            *(process(client, semaphore, url, include_raw) for url in urls)
        )

    push_data(results)

    scored = [r for r in results if r.get("fetched")]
    if scored:
        average = round(sum(r["score"] for r in scored) / len(scored), 1)
        failed = sum(1 for r in scored if r["grade"] == "F")
        set_status_message(
            f"Checked {len(scored)} page(s). Average score {average}/100, {failed} page(s) graded F."
        )
        print(f"Average structured-data score: {average}/100")


if __name__ == "__main__":
    asyncio.run(main())
