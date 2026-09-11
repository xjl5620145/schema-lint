#!/usr/bin/env python3
"""
Upload schema-lint to Apify via REST API.

No apify-cli, no npm, no browser login needed. Pure stdlib.

Usage:
    export APIFY_TOKEN=apify_api_xxxxxxxxxxxx
    python tools/push_via_api.py

Get your token at:
    Apify Console -> Settings -> API & Integrations -> Personal API tokens -> Create
    (copy the one starting with "apify_api_")

What it does:
    1. Finds an existing actor named schema-lint in your account, or creates one
    2. Uploads every project file as a new version (sourceType = SOURCE_FILES)
    3. Tags the build as "latest" so you can run it right away
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

API = "https://api.apify.com/v2"
ACTOR_NAME = "schema-lint"
VERSION = "0.1"
ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", ".idea", ".mypy_cache", ".pytest_cache"}
SKIP_FILES = {".DS_Store", "push_via_api.py"}


def request(method, path, token, payload=None):
    url = f"{API}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body[:400]}


def collect_files():
    files = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.name in SKIP_FILES:
            continue
        files.append({
            "name": rel.as_posix(),
            "format": "TEXT",
            "content": p.read_text(encoding="utf-8"),
        })
    return files


def find_actor(token):
    status, data = request("GET", "/acts?my=true&limit=100", token)
    if status != 200:
        return None, f"cannot list actors (HTTP {status}): {data}"
    for item in data.get("data", {}).get("items", []):
        if item.get("name") == ACTOR_NAME:
            return item, None
    return None, None


def create_actor(token):
    payload = {
        "name": ACTOR_NAME,
        "title": "Schema.org & JSON-LD Validator",
        "description": (
            "Extract and validate structured data (JSON-LD) from any URL in bulk. "
            "Reports missing fields Google requires for rich results, plus a 0-100 score per page."
        ),
        "isPublic": False,
        "isAnonymouslyRunnable": False,
    }
    status, data = request("POST", "/acts", token)
    if status in (200, 201):
        return data.get("data"), None
    return None, f"HTTP {status}: {data}"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    token = os.environ.get("APIFY_TOKEN") or (args[0] if args else "")
    if not token:
        print("ERROR: no token.\n"
              "  export APIFY_TOKEN=apify_api_xxxx   then run again.\n"
              "  Get it from Console -> Settings -> API & Integrations -> Personal API tokens")
        return 1
    if not token.startswith("apify_api_"):
        print(f"WARNING: token looks unusual (starts with {token[:6]}...), continuing anyway")

    files = collect_files()
    print(f"Collected {len(files)} files:")
    for f in files:
        print(f"  {f['name']:32s} {len(f['content']):6d} chars")

    if "--dry-run" in sys.argv:
        print("\n--dry-run: nothing uploaded.")
        return 0

    actor, err = find_actor(token)
    if err:
        print(f"ERROR: {err}")
        return 1

    if actor:
        print(f"\nFound existing actor: {actor.get('username')}~{actor.get('name')} ({actor.get('id')})")
    else:
        print("\nNo existing actor, creating...")
        actor, err = create_actor(token)
        if err:
            print(f"ERROR creating actor: {err}")
            return 1
        print(f"Created: {actor.get('username')}~{actor.get('name')} ({actor.get('id')})")

    actor_id = actor.get("id")
    print(f"\nUploading version {VERSION} to {actor_id} ...")
    status, data = request("POST", f"/acts/{actor_id}/versions", token, {
        "versionNumber": VERSION,
        "sourceType": "SOURCE_FILES",
        "sourceFiles": files,
        "buildTag": "latest",
    })

    if status not in (200, 201):
        print(f"ERROR uploading version (HTTP {status}): {json.dumps(data, ensure_ascii=False)[:600]}")
        return 1

    print("Version uploaded. Apify is building the Docker image now (1-3 min).")
    print(f"\nOpen: https://console.apify.com/actors/{actor_id}")
    print("Then: Input tab -> paste a URL -> Start -> check the Output tab")
    return 0


if __name__ == "__main__":
    sys.exit(main())
