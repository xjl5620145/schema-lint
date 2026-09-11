"""End-to-end check without the Apify SDK.

Lets you verify the whole thing on real pages before you ever install `apify`
or push a Docker image. Only needs httpx.

    pip install httpx
    python src/smoke.py https://example.com https://news.ycombinator.com
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validator import lint_html  # noqa: E402

USER_AGENT = (
    "Mozilla/5.0 (compatible; SchemaLint/0.1) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


async def check(client: httpx.AsyncClient, url: str) -> None:
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        print(f"{url}\n  FAILED  {type(exc).__name__}: {exc}\n")
        return

    report = lint_html(response.text)
    print(f"{url}")
    print(f"  status={response.status_code}  grade={report['grade']}  score={report['score']}/100")
    print(f"  blocks={report['jsonLdBlockCount']}  types={report['types'] or 'none'}")
    for issue in report["issues"][:8]:
        print(f"    [{issue['severity']:7s}] {issue['field']} - {issue['message']}")
    if report["errorCount"] + report["warningCount"] > 8:
        print(f"    ... {report['errorCount'] + report['warningCount'] - 8} more")
    print()


async def main(urls: list[str]) -> None:
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=20, headers={"user-agent": USER_AGENT}
    ) as client:
        for url in urls:
            await check(client, url)


if __name__ == "__main__":
    targets = sys.argv[1:] or ["https://example.com"]
    asyncio.run(main(targets))
