"""GitHub integration -- read-only via PyGithub.

Powers the code-reviewer skill: lists recent commits on assignment repos
and surfaces diffs for review. Set GITHUB_ASSIGNMENT_REPOS=owner/repo1,owner/repo2
in .env to scope which repos the code reviewer touches."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _env  # noqa: F401, E402

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])


def _get_client():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN not set in .env", file=sys.stderr)
        return None
    try:
        from github import Auth, Github
    except ImportError:
        print("PyGithub not installed: py -m pip install -r .claude/requirements.txt", file=sys.stderr)
        return None
    return Github(auth=Auth.Token(token))


def _assignment_repos() -> list[str]:
    raw = os.environ.get("GITHUB_ASSIGNMENT_REPOS", "").strip()
    if not raw:
        return []
    return [r.strip() for r in raw.split(",") if r.strip()]


def _resolve_targets(g, repos: list[str] | None) -> list[str]:
    if repos:
        return repos
    target = _assignment_repos()
    if target:
        return target
    return [r.full_name for r in g.get_user().get_repos()][:20]


def _all_user_repos(g, *, limit: int = 30) -> list[str]:
    """All repos the authenticated token can see, sorted by recent push.
    Capped to `limit` so we don't blow the rate budget on a long history
    of stale forks. Slice 5 (#pr-activity) uses this -- it intentionally
    ignores GITHUB_ASSIGNMENT_REPOS, which is scoped to code-reviewer."""
    try:
        repos = g.get_user().get_repos(sort="pushed", direction="desc")
    except Exception as exc:
        print(f"_all_user_repos failed: {exc}", file=sys.stderr)
        return []
    out: list[str] = []
    for r in repos:
        out.append(r.full_name)
        if len(out) >= limit:
            break
    return out


def recent_pr_events(repos: list[str] | None = None, since: float | None = None) -> list[dict]:
    """PR transitions and comments across `repos` since `since` (epoch s).

    Emits three event kinds with stable dedupe ids:
      pr_opened     id=f"open:{repo}:{number}"    -- PR created since cutoff
      pr_merged     id=f"merge:{repo}:{number}"   -- PR merged since cutoff
      pr_comment    id=f"comment:{comment_id}"    -- new issue/PR comment

    Empty `repos` falls back to _all_user_repos(g). Sorted oldest first so
    the dedupe consumer adds events in chronological order."""
    g = _get_client()
    if not g:
        return []
    if since is None:
        since = (datetime.now(timezone.utc) - timedelta(days=1)).timestamp()
    since_dt = datetime.fromtimestamp(since, tz=timezone.utc)

    targets = repos if repos else _all_user_repos(g)
    out: list[dict] = []
    for full_name in targets:
        try:
            repo = g.get_repo(full_name)
        except Exception as exc:
            print(f"recent_pr_events: get_repo({full_name}) failed: {exc}", file=sys.stderr)
            continue

        # PRs updated since cutoff -- pulls opens and merges with one walk.
        try:
            for pr in repo.get_pulls(state="all", sort="updated", direction="desc"):
                updated = pr.updated_at.replace(tzinfo=timezone.utc)
                if updated < since_dt:
                    break
                created = pr.created_at.replace(tzinfo=timezone.utc)
                if created >= since_dt:
                    out.append({
                        "id": f"open:{full_name}:{pr.number}",
                        "kind": "pr_opened",
                        "repo": full_name,
                        "pr_number": pr.number,
                        "pr_title": pr.title or "",
                        "pr_url": pr.html_url,
                        "actor": pr.user.login if pr.user else "",
                        "ts": created.timestamp(),
                    })
                if pr.merged_at:
                    merged = pr.merged_at.replace(tzinfo=timezone.utc)
                    if merged >= since_dt:
                        actor = ""
                        if pr.merged_by:
                            actor = pr.merged_by.login
                        elif pr.user:
                            actor = pr.user.login
                        out.append({
                            "id": f"merge:{full_name}:{pr.number}",
                            "kind": "pr_merged",
                            "repo": full_name,
                            "pr_number": pr.number,
                            "pr_title": pr.title or "",
                            "pr_url": pr.html_url,
                            "actor": actor,
                            "ts": merged.timestamp(),
                        })
        except Exception as exc:
            print(f"recent_pr_events: get_pulls({full_name}) failed: {exc}", file=sys.stderr)

        # Issue comments since cutoff -- filter to those on PRs by URL shape.
        try:
            for c in repo.get_issues_comments(since=since_dt):
                if "/pull/" not in (c.html_url or ""):
                    continue
                try:
                    pr_num = int(c.html_url.split("/pull/")[1].split("#", 1)[0].rstrip("/").split("/", 1)[0])
                except (ValueError, IndexError):
                    continue
                out.append({
                    "id": f"comment:{c.id}",
                    "kind": "pr_comment",
                    "repo": full_name,
                    "pr_number": pr_num,
                    "pr_title": "",
                    "pr_url": c.html_url,
                    "actor": c.user.login if c.user else "",
                    "ts": c.created_at.replace(tzinfo=timezone.utc).timestamp(),
                })
        except Exception as exc:
            print(f"recent_pr_events: get_issues_comments({full_name}) failed: {exc}", file=sys.stderr)

    out.sort(key=lambda e: e.get("ts", 0))
    return out


def recent_pushes(days: int = 7, repos: list[str] | None = None) -> list[dict]:
    g = _get_client()
    if not g:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[dict] = []
    for full_name in _resolve_targets(g, repos):
        try:
            repo = g.get_repo(full_name)
            for commit in repo.get_commits(since=since):
                out.append({
                    "repo": full_name,
                    "sha": commit.sha[:7],
                    "author": commit.commit.author.name,
                    "date": commit.commit.author.date.isoformat(),
                    "message": commit.commit.message.splitlines()[0][:120],
                })
        except Exception as exc:
            out.append({"repo": full_name, "error": str(exc)})
    out.sort(key=lambda c: c.get("date", ""), reverse=True)
    return out


def pr_list(repo_name: str | None = None) -> list[dict]:
    g = _get_client()
    if not g:
        return []
    out: list[dict] = []
    targets = [repo_name] if repo_name else _resolve_targets(g, None)
    for full_name in targets:
        try:
            repo = g.get_repo(full_name)
            for pr in repo.get_pulls(state="open"):
                out.append({
                    "repo": full_name,
                    "number": pr.number,
                    "title": pr.title,
                    "author": pr.user.login,
                    "url": pr.html_url,
                    "updated": pr.updated_at.isoformat(),
                })
        except Exception as exc:
            out.append({"repo": full_name, "error": str(exc)})
    return out


def diff(repo_name: str, sha: str) -> dict:
    g = _get_client()
    if not g:
        return {"error": "no client"}
    try:
        repo = g.get_repo(repo_name)
        commit = repo.get_commit(sha)
        return {
            "repo": repo_name,
            "sha": commit.sha,
            "author": commit.commit.author.name,
            "date": commit.commit.author.date.isoformat(),
            "message": commit.commit.message,
            "files": [
                {
                    "filename": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "patch": (f.patch or "")[:8000],
                }
                for f in commit.files
            ],
        }
    except Exception as exc:
        return {"repo": repo_name, "sha": sha, "error": str(exc)}


def latest_workflow_run(repo_name: str, workflow_file: str = "build.yml") -> dict | None:
    """Status of the most recent run of `workflow_file` in repo_name. None
    if the client isn't available, the repo/workflow has no runs, or the
    API call fails for any reason."""
    g = _get_client()
    if not g:
        return None
    try:
        repo = g.get_repo(repo_name)
        workflow = repo.get_workflow(workflow_file)
        runs = list(workflow.get_runs()[:1])
    except Exception as exc:
        print(f"latest_workflow_run({repo_name}) failed: {exc}", file=sys.stderr)
        return None
    if not runs:
        return None
    run = runs[0]
    return {
        "status": run.status,
        "conclusion": run.conclusion,
        "html_url": run.html_url,
        "created_at": run.created_at.isoformat(),
    }


def handle_query(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="query.py github")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    p_rp = sub.add_parser("recent-pushes")
    p_rp.add_argument("--days", type=int, default=7)
    p_pr = sub.add_parser("pr-list")
    p_pr.add_argument("repo", nargs="?")
    p_d = sub.add_parser("diff")
    p_d.add_argument("repo")
    p_d.add_argument("sha")
    p_ws = sub.add_parser("workflow-status")
    p_ws.add_argument("repo")
    p_ws.add_argument("--workflow", default="build.yml")
    p_pe = sub.add_parser("pr-events")
    p_pe.add_argument("--repos", default="")
    p_pe.add_argument("--since", type=float, default=None)
    p_pe.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    json_out = args.json

    if args.subcommand == "recent-pushes":
        rows = recent_pushes(days=args.days)
        if json_out:
            print(json.dumps(rows, indent=2, default=str))
        else:
            for r in rows:
                if "error" in r:
                    print(f"!! {r['repo']}: {r['error']}")
                else:
                    print(f"{r['date'][:10]}  {r['repo']}  {r['sha']}  {r['author']}: {r['message']}")
    elif args.subcommand == "pr-list":
        rows = pr_list(args.repo)
        if json_out:
            print(json.dumps(rows, indent=2, default=str))
        else:
            for r in rows:
                if "error" in r:
                    print(f"!! {r['repo']}: {r['error']}")
                else:
                    print(f"#{r['number']:<5}  {r['repo']}  by {r['author']}  -- {r['title']}")
    elif args.subcommand == "diff":
        result = diff(args.repo, args.sha)
        print(json.dumps(result, indent=2, default=str))
    elif args.subcommand == "workflow-status":
        result = latest_workflow_run(args.repo, args.workflow)
        print(json.dumps(result, indent=2, default=str))
    elif args.subcommand == "pr-events":
        repos = [r.strip() for r in args.repos.split(",") if r.strip()] or None
        rows = recent_pr_events(repos=repos, since=args.since)
        if json_out:
            print(json.dumps(rows, default=str))
        else:
            for r in rows:
                print(f"{r['kind']}: {r['repo']}#{r['pr_number']} {r['pr_title']}")
    return 0


if __name__ == "__main__":
    sys.exit(handle_query(sys.argv[1:]))
