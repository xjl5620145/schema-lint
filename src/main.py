"""Apify Actor entrypoint: fetch each URL and lint its structured data."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

import httpx
from apify import Actor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validator import lint_html  # noqa: E402

USER_AGENT = (
    "Mozilla/5.0 (compatible; SchemaLint/0.1; +https://apify.com) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


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
    async with Actor:
        actor_input = await Actor.get_input() or {}
        urls = [u.strip() for u in (actor_input.get("urls") or []) if str(u).strip()]
        if not urls:
            raise ValueError("No URLs provided. Pass a non-empty 'urls' array.")

        max_concurrency = max(1, int(actor_input.get("maxConcurrency", 5)))
        timeout_ms = max(1000, int(actor_input.get("timeoutMs", 20000)))
        include_raw = bool(actor_input.get("includeRawBlocks", False))

        Actor.log.info(f"Checking structured data on {len(urls)} URL(s)")

        semaphore = asyncio.Semaphore(max_concurrency)
        limits = httpx.Limits(max_connections=max_concurrency, max_keepalive_connections=max_concurrency)

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout_ms / 1000,
            limits=limits,
            headers={"user-agent": USER_AGENT, "accept": "text/html,application/xhtml+xml"},
        ) as client:
            results = await asyncio.gather(
                *(process(client, semaphore, url, include_raw) for url in urls),
                return_exceptions=False,
            )

        for item in results:
            await Actor.push_data(item)

        scored = [r for r in results if r.get("fetched")]
        if scored:
            average = round(sum(r["score"] for r in scored) / len(scored), 1)
            failed = sum(1 for r in scored if r["grade"] == "F")
            await Actor.set_status_message(
                f"Checked {len(scored)} page(s). Average score {average}/100, {failed} page(s) graded F."
            )
            Actor.log.info(f"Average structured-data score: {average}/100")


if __name__ == "__main__":
    asyncio.run(main())
