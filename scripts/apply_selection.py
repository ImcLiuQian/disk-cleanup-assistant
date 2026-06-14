#!/usr/bin/env python3
"""Apply a saved disk cleanup selection and optionally run git gc."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path


CONFIRM_DELETE_TOKEN = "DELETE_SELECTED_PATHS"
PROTECTED = {Path("/"), Path("/System"), Path("/Library"), Path("/usr"), Path("/bin"), Path("/sbin")}


def load_candidates(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("candidates", data if isinstance(data, list) else [])
    return {item["id"]: item for item in items}


def run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=timeout)


def is_protected(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    for protected in PROTECTED:
        if protected == Path("/"):
            if resolved == protected:
                return True
            continue
        if resolved == protected or protected in resolved.parents:
            return True
    return False


def collapse_selected(paths: list[tuple[str, Path]]) -> tuple[list[tuple[str, Path]], dict[str, str]]:
    selected = sorted(paths, key=lambda x: len(x[1].parts))
    kept: list[tuple[str, Path]] = []
    covered: dict[str, str] = {}
    for item_id, path in selected:
        parent = next((kept_id for kept_id, kept_path in kept if path != kept_path and kept_path in path.parents), None)
        if parent:
            covered[item_id] = parent
        else:
            kept.append((item_id, path))
    return kept, covered


def make_dirs_writable(path: Path) -> dict:
    result = run(["find", str(path), "-type", "d", "-exec", "chmod", "u+w", "{}", "+"])
    return {"returncode": result.returncode, "stderr": result.stderr.strip()}


def kill_go_cache_users(path: Path) -> dict:
    result = run(["lsof", "-t", "+D", str(path)])
    pids = sorted({pid.strip() for pid in result.stdout.splitlines() if pid.strip()})
    killed: list[str] = []
    skipped: list[str] = []
    for pid in pids:
        ps = run(["ps", "-p", pid, "-o", "comm="])
        name = Path(ps.stdout.strip()).name
        if name in {"go", "git", "ssh"}:
            kill = run(["kill", pid])
            if kill.returncode == 0:
                killed.append(pid)
            else:
                skipped.append(f"{pid}:{kill.stderr.strip()}")
        else:
            skipped.append(f"{pid}:{name}")
    return {"pids": pids, "killed": killed, "skipped": skipped}


def delete_path(path: Path, dry_run: bool, kill_cache_users: bool) -> dict:
    if is_protected(path):
        return {"status": "blocked", "reason": "protected path"}
    if not path.exists() and not path.is_symlink():
        return {"status": "missing"}
    if dry_run:
        return {"status": "dry-run"}

    preflight: dict[str, object] = {}
    if str(path).endswith("/go/pkg/mod"):
        preflight["chmod_dirs"] = make_dirs_writable(path)
        if kill_cache_users:
            preflight["killed_cache_users"] = kill_go_cache_users(path)

    rm = run(["rm", "-rf", str(path)])
    exists_after = path.exists() or path.is_symlink()
    if rm.returncode != 0 and str(path).endswith("/go/pkg/mod") and kill_cache_users:
        preflight["retry_chmod_dirs"] = make_dirs_writable(path)
        rm = run(["rm", "-rf", str(path)])
        exists_after = path.exists() or path.is_symlink()
    return {
        "status": "deleted" if rm.returncode == 0 and not exists_after else "failed",
        "returncode": rm.returncode,
        "stderr": rm.stderr.strip(),
        "exists_after": exists_after,
        "preflight": preflight,
    }


def find_git_repos(root: Path) -> list[Path]:
    repos: list[Path] = []
    if not root.exists():
        return repos
    for current, dirs, _files in os.walk(root):
        if ".git" in dirs:
            repos.append(Path(current))
            dirs[:] = []
    return sorted(repos)


def git_gc(repo: Path, dry_run: bool, timeout: int) -> dict:
    if dry_run:
        return {"repo": str(repo), "status": "dry-run"}
    result = run(["git", "-C", str(repo), "gc", "--prune=now"], timeout=timeout)
    return {
        "repo": str(repo),
        "status": "ok" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--git-gc-root", type=Path)
    parser.add_argument("--git-gc-timeout", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--confirm-delete",
        help=f"Required for destructive execution. Must be exactly {CONFIRM_DELETE_TOKEN}.",
    )
    parser.add_argument("--kill-go-cache-users", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.dry_run and args.confirm_delete != CONFIRM_DELETE_TOKEN:
        report = {
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "dry_run": args.dry_run,
            "selection": str(args.selection),
            "status": "blocked",
            "reason": "missing or invalid --confirm-delete token",
            "expected_confirm_delete": CONFIRM_DELETE_TOKEN,
            "delete_results": [],
            "git_gc_repo_count": 0,
            "git_gc_results": [],
        }
        args.log.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    candidates = load_candidates(args.candidates)
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    selected_ids = selection.get("delete_ids", [])
    selected_paths = [(item_id, Path(candidates[item_id]["path"])) for item_id in selected_ids if item_id in candidates]
    delete_targets, covered = collapse_selected(selected_paths)

    delete_results = []
    for item_id, path in delete_targets:
        result = delete_path(path, args.dry_run, args.kill_go_cache_users)
        delete_results.append({"id": item_id, "path": str(path), **result})
    for item_id, parent_id in covered.items():
        delete_results.append({"id": item_id, "status": "covered-by-parent", "parent_id": parent_id})

    gc_results: list[dict] = []
    if args.git_gc_root:
        gc_results = [git_gc(repo, args.dry_run, args.git_gc_timeout) for repo in find_git_repos(args.git_gc_root)]

    report = {
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": args.dry_run,
        "selection": str(args.selection),
        "delete_results": delete_results,
        "git_gc_repo_count": len(gc_results),
        "git_gc_results": gc_results,
    }
    args.log.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "selected_count": len(selected_ids),
        "attempted_delete_count": len(delete_targets),
        "covered_count": len(covered),
        "deleted_count": len([x for x in delete_results if x.get("status") == "deleted"]),
        "missing_count": len([x for x in delete_results if x.get("status") == "missing"]),
        "blocked_count": len([x for x in delete_results if x.get("status") == "blocked"]),
        "failed_count": len([x for x in delete_results if x.get("status") == "failed"]),
        "failed_deletes": [x for x in delete_results if x.get("status") == "failed"],
        "git_gc_repo_count": len(gc_results),
        "failed_gc": [x for x in gc_results if x.get("status") == "failed"],
        "log": str(args.log),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failed_deletes"] or summary["failed_gc"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
