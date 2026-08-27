#!/usr/bin/env python3
"""Fetch the live numbers from the GitHub GraphQL API and write stats.json (build_svg.py renders it).

Environment:
  ACCESS_TOKEN      GitHub token. A classic PAT with `repo` + `read:user` (+ `read:org` for org repos),
                    or a fine-grained token with read access to contents/metadata of the repos you care about.
  USER_NAME         GitHub login to report on (normally the token owner).
  LOC_AFFILIATIONS  Repos to walk for lines of code and language bytes: comma-separated subset of
                    OWNER,COLLABORATOR,ORGANIZATION_MEMBER (default: OWNER).
  EXCLUDE_REPOS     Comma-separated owner/name list to skip.

cache/loc.json memoises the lines-of-code walk per repository; its keys are hashes, so private
repo names never end up in this (public) repo.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
API = "https://api.github.com/graphql"
CACHE_FILE = ROOT / "cache" / "loc.json"
STATS_FILE = ROOT / "stats.json"
UTC = dt.timezone.utc

TOKEN = os.environ.get("ACCESS_TOKEN")
USER = os.environ.get("USER_NAME")
LOC_AFFILIATIONS = [a.strip() for a in os.environ.get("LOC_AFFILIATIONS", "OWNER").split(",") if a.strip()]
EXCLUDE_REPOS = {r.strip() for r in os.environ.get("EXCLUDE_REPOS", "").split(",") if r.strip()}

session = requests.Session()
session.headers["Authorization"] = f"bearer {TOKEN}"


def gql(query: str, variables: dict) -> dict:
    for attempt in range(6):
        r = session.post(API, json={"query": query, "variables": variables}, timeout=60)
        if r.status_code == 401:
            sys.exit("GitHub rejected ACCESS_TOKEN (401). Check the secret and its scopes.")
        throttled = r.status_code in (403, 429) and "rate limit" in r.text.lower()
        if r.status_code >= 500 or throttled:
            wait = int(r.headers.get("Retry-After") or 0) or min(300, 10 * 2 ** attempt)
            print(f"  GitHub replied {r.status_code}; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        r.raise_for_status()
        payload = r.json()
        if payload.get("errors") and not payload.get("data"):
            raise RuntimeError(json.dumps(payload["errors"], indent=2))
        return payload["data"]
    raise RuntimeError("GitHub GraphQL API kept failing")


# ---- profile numbers ----------------------------------------------------------------------

OVERVIEW_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    id
    createdAt
    followers { totalCount }
    repositoriesContributedTo(
      first: 1, includeUserRepositories: false,
      contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]
    ) { totalCount }
    repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER]) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { stargazerCount }
    }
  }
}
"""


def overview() -> dict:
    cursor, stars, first = None, 0, None
    while True:
        user = gql(OVERVIEW_QUERY, {"login": USER, "cursor": cursor})["user"]
        if user is None:
            sys.exit(f"GitHub user '{USER}' not found.")
        first = first or user
        repos = user["repositories"]
        stars += sum(n["stargazerCount"] for n in repos["nodes"])
        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]
    return {
        "id": first["id"],
        "created_at": first["createdAt"],
        "followers": first["followers"]["totalCount"],
        "contributed": first["repositoriesContributedTo"]["totalCount"],
        "repos": first["repositories"]["totalCount"],
        "stars": stars,
    }


def total_commits(created_at: dt.datetime) -> int:
    """Commit contributions per calendar year since the account was created, in one request."""
    now = dt.datetime.now(UTC)
    stamp = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    aliases = []
    for year in range(created_at.year, now.year + 1):
        start = max(created_at, dt.datetime(year, 1, 1, tzinfo=UTC))
        end = min(now, dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC))
        aliases.append(f'y{year}: contributionsCollection(from: "{stamp(start)}", to: "{stamp(end)}") '
                       "{ totalCommitContributions }")
    query = "query($login: String!) { user(login: $login) { %s } }" % " ".join(aliases)
    years = gql(query, {"login": USER})["user"]
    return sum(v["totalCommitContributions"] for v in years.values())


ACTIVITY_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}
"""


def activity(days: int = 30) -> tuple[list[int], list[int]]:
    """Daily contribution counts for the last `days` days (oldest first) and 1/7/30-day totals."""
    now = dt.datetime.now(UTC)
    calendar = gql(ACTIVITY_QUERY, {"login": USER, "from": (now - dt.timedelta(days=days + 7)).isoformat(),
                                    "to": now.isoformat()})["user"]["contributionsCollection"]["contributionCalendar"]
    counts = sorted((d["date"], d["contributionCount"]) for w in calendar["weeks"] for d in w["contributionDays"])
    series = [c for _, c in counts][-days:]
    return series, [sum(series[-1:]), sum(series[-7:]), sum(series)]


# ---- repositories: lines of code + language bytes ---------------------------------------------

REPOS_QUERY = """
query($login: String!, $cursor: String, $affiliations: [RepositoryAffiliation]) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, affiliations: $affiliations, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        defaultBranchRef { target { ... on Commit { oid } } }
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

HISTORY_QUERY = """
query($owner: String!, $name: String!, $author: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor, author: {id: $author}) {
            totalCount
            pageInfo { hasNextPage endCursor }
            nodes { oid additions deletions parents(first: 1) { totalCount } }
          }
        }
      }
    }
  }
}
"""


def list_repos() -> list[dict]:
    cursor, out = None, []
    while True:
        repos = gql(REPOS_QUERY, {"login": USER, "cursor": cursor,
                                  "affiliations": LOC_AFFILIATIONS})["user"]["repositories"]
        for node in repos["nodes"]:
            if node["nameWithOwner"] in EXCLUDE_REPOS or not node["defaultBranchRef"]:
                continue
            out.append({"name": node["nameWithOwner"], "head": node["defaultBranchRef"]["target"]["oid"],
                        "languages": node["languages"]["edges"]})
        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]
    return out


def walk_repo(full_name: str, author_id: str, cached: dict | None) -> dict:
    """Additions/deletions of the user's commits on the default branch (merge commits excluded).

    Walks newest-first and stops as soon as it meets the newest commit recorded in the cache,
    so after the first run only new commits are fetched.
    """
    owner, name = full_name.split("/", 1)
    stats = {"my_head": None, "commits": 0, "additions": 0, "deletions": 0}
    cursor, total, reached_cache = None, 0, False
    while True:
        repo = gql(HISTORY_QUERY, {"owner": owner, "name": name, "author": author_id, "cursor": cursor})["repository"]
        target = ((repo or {}).get("defaultBranchRef") or {}).get("target") or {}
        history = target.get("history")
        if not history:
            break
        total = history["totalCount"]
        for node in history["nodes"]:
            stats["my_head"] = stats["my_head"] or node["oid"]
            if cached and node["oid"] == cached.get("my_head"):
                reached_cache = True
                break
            stats["commits"] += 1
            if node["parents"]["totalCount"] <= 1:  # merge commits would double count everything
                stats["additions"] += node["additions"]
                stats["deletions"] += node["deletions"]
        if reached_cache or not history["pageInfo"]["hasNextPage"]:
            break
        cursor = history["pageInfo"]["endCursor"]

    if reached_cache:
        for key in ("commits", "additions", "deletions"):
            stats[key] += cached[key]
        if stats["commits"] != total:  # history was rewritten; the cache can't be trusted
            return walk_repo(full_name, author_id, None)
    return stats


def repositories(author_id: str) -> tuple[int, int, list[dict]]:
    """(additions, deletions, languages sorted by bytes) across the repos in LOC_AFFILIATIONS."""
    cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
    fresh, additions, deletions, langs = {}, 0, 0, {}
    for repo in list_repos():
        key = hashlib.sha256(f"{USER}:{repo['name']}".encode()).hexdigest()[:16]
        entry = cache.get(key)
        if not entry or entry.get("head") != repo["head"]:
            print(f"  walking {repo['name']}", file=sys.stderr)
            entry = {"head": repo["head"], **walk_repo(repo["name"], author_id, entry)}
        fresh[key] = entry
        additions += entry["additions"]
        deletions += entry["deletions"]
        for edge in repo["languages"]:
            lang = langs.setdefault(edge["node"]["name"], {"name": edge["node"]["name"],
                                                            "color": edge["node"]["color"], "bytes": 0})
            lang["bytes"] += edge["size"]
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(fresh, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return additions, deletions, sorted(langs.values(), key=lambda l: -l["bytes"])


def main():
    if not TOKEN or not USER:
        sys.exit("Set ACCESS_TOKEN and USER_NAME.")
    print("Fetching profile…")
    info = overview()
    created_at = dt.datetime.fromisoformat(info["created_at"].replace("Z", "+00:00"))
    print("Counting commits…")
    commits = total_commits(created_at)
    print("Reading the contribution calendar…")
    series, load = activity()
    print("Walking repositories (lines of code, languages)…")
    additions, deletions, langs = repositories(info["id"])

    stats = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "login": USER,
        "created_at": info["created_at"],
        "repos": info["repos"],
        "contributed": info["contributed"],
        "stars": info["stars"],
        "commits": commits,
        "followers": info["followers"],
        "additions": additions,
        "deletions": deletions,
        "activity": series,
        "load": load,
        "languages": langs,
    }
    STATS_FILE.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k not in ("activity", "languages")}, indent=2))


if __name__ == "__main__":
    main()
