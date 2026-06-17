#!/usr/bin/env python3
"""
Upload YouTube transcripts from GitHub directly into a Claude Project.

Runs automatically via GitHub Actions when new transcripts are pushed.
Can also be run manually:
  CLAUDE_SESSION_KEY="sk-ant-sid01-..." python3 upload_to_project.py
"""

import os
import sys
import time
import requests

ORG_ID = "4a4ad5e5-e6ce-4ae0-9652-b6e125127c89"
PROJECT_ID = "019d43d8-8558-713d-9552-0b6420df1af6"
GITHUB_USER = "ninjatre255-cmd"
GITHUB_REPO = "isaac-transcript-bot"
GITHUB_BRANCH = "main"
TRANSCRIPTS_PATH = "transcripts"

DOCS_URL = f"https://claude.ai/api/organizations/{ORG_ID}/projects/{PROJECT_ID}/docs"


def get_session(session_key: str) -> requests.Session:
    s = requests.Session()
    s.cookies.set("sessionKey", session_key, domain="claude.ai")
    s.headers.update({"Content-Type": "application/json"})
    return s


def fetch_github_files(token: str | None = None) -> list[dict]:
    url = (
        f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}"
        f"/contents/{TRANSCRIPTS_PATH}?ref={GITHUB_BRANCH}"
    )
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return [f for f in resp.json() if f["name"].endswith(".txt")]


def get_existing_docs(session: requests.Session) -> set[str]:
    resp = session.get(DOCS_URL, timeout=30)
    if resp.status_code == 401:
        print("ERROR: CLAUDE_SESSION_KEY is invalid or expired.")
        print("Get a fresh one from claude.ai > DevTools > Application > Cookies > sessionKey")
        sys.exit(1)
    resp.raise_for_status()
    return {d["file_name"] for d in resp.json()}


def upload_doc(session: requests.Session, name: str, content: str) -> bool:
    resp = session.post(DOCS_URL, json={"file_name": name, "content": content}, timeout=30)
    return resp.status_code == 201


def main() -> None:
    session_key = os.environ.get("CLAUDE_SESSION_KEY")
    if not session_key:
        print("ERROR: CLAUDE_SESSION_KEY environment variable not set.")
        print("Add it as a GitHub Actions secret named CLAUDE_SESSION_KEY.")
        sys.exit(1)

    github_token = os.environ.get("GITHUB_TOKEN")

    session = get_session(session_key)

    print("Checking existing project docs...")
    existing = get_existing_docs(session)
    print(f"  {len(existing)} docs already in project")

    print("Fetching transcript list from GitHub...")
    github_files = fetch_github_files(github_token)
    print(f"  {len(github_files)} .txt files found")

    uploaded = skipped = failed = 0
    for file_info in github_files:
        name = file_info["name"]
        if name in existing:
            print(f"  [skip] {name}")
            skipped += 1
            continue

        content = requests.get(file_info["download_url"], timeout=30).text
        if upload_doc(session, name, content):
            print(f"  [done] {name}")
            uploaded += 1
        else:
            print(f"  [FAIL] {name}")
            failed += 1
        time.sleep(0.3)

    print(f"Result: {uploaded} uploaded, {skipped} skipped, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
