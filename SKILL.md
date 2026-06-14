---
name: disk-cleanup-assistant
description: Mac disk cleanup workflow. Use when the user asks an assistant to analyze low disk space, scan all large directories or files over a threshold, provide an interactive delete/not-delete selector, remove user-approved cleanup candidates, clean developer caches, or run git gc across project directories.
---

# Disk Cleanup Assistant

## Overview

Use this skill for end-to-end, auditable Mac disk cleanup. The default flow is:
scan first, classify candidates, let the user choose interactively, delete only after an explicit delete instruction, run optional `git gc`, then verify free space and report evidence.

## Safety Rules

- Treat scanning as read-only.
- Never delete from scan results alone. Require both a saved selection and a later explicit user instruction such as "start deleting".
- When applying a destructive selection, pass `--confirm-delete DELETE_SELECTED_PATHS`. Without this exact token, `apply_selection.py` must block and delete nothing.
- Use normal user permissions by default. Do not use `sudo`.
- Treat `/`, `/System`, `/Library`, `/usr`, `/bin`, `/sbin`, and all descendants or symlink targets under them as protected.
- Ask for or request approval before destructive commands when the sandbox requires it.
- Tag personal data locations such as `Documents`, `Desktop`, `Downloads`, browser profiles, Photos libraries, Mail, and app support data as review-only unless the user explicitly selects them.
- Expect running apps to recreate cache/log directories. Verify size after deletion; a recreated empty directory is not a failure.
- For Go module cache, watch for GoLand or `go list` rebuilding `~/go/pkg/mod/cache/vcs`. If deletion fails because active `go`, `git`, or `ssh` child processes hold that path, identify the exact processes with `lsof`/`ps` and terminate only those cache-related child processes after the user has approved deleting that cache.

## Workflow

1. Establish baseline:

```bash
df -h /System/Volumes/Data
```

2. Scan large items:

```bash
python3 scripts/scan_large_items.py \
  --threshold-gb 1 \
  --depth 5 \
  --output /Users/bytedance/Documents/Playground/disk_cleanup_candidates.json \
  --markdown /Users/bytedance/Documents/Playground/disk_cleanup_candidates.md
```

Use targeted `--roots` when the user narrows scope, for example `--roots /Users/bytedance/my_project /Users/bytedance/Library/Caches`.

3. Give the user an interactive choice UI when they ask for "交互", "选项", "删 or 不删", or similar:

```bash
python3 scripts/selector_server.py \
  --candidates /Users/bytedance/Documents/Playground/disk_cleanup_candidates.json \
  --selection /Users/bytedance/Documents/Playground/disk_cleanup_selection.json \
  --port 8765
```

Open or share `http://127.0.0.1:8765/`. Keep the server running until the user saves choices. Stop it after cleanup.

4. Apply the saved selection only after the user says to delete:

```bash
python3 scripts/apply_selection.py \
  --candidates /Users/bytedance/Documents/Playground/disk_cleanup_candidates.json \
  --selection /Users/bytedance/Documents/Playground/disk_cleanup_selection.json \
  --log /Users/bytedance/Documents/Playground/disk_cleanup_apply_log.json \
  --git-gc-root /Users/bytedance/my_project \
  --confirm-delete DELETE_SELECTED_PATHS
```

Use `--dry-run` before destructive execution if the selection is surprising. Use `--kill-go-cache-users` only for selected Go module cache cleanup when active GoLand/go child processes are confirmed to be rebuilding the cache.

5. Verify:

- Run `df -h /System/Volumes/Data`.
- Check selected paths exist or were recreated small.
- Merge multiple `git gc` attempts by repo: a repo is complete if any attempt logged `status: ok`.
- Save a short final summary JSON with final disk state, selected paths, deletion notes, `git gc` repo count, and failures.
- Send a Feishu completion card when the user's workspace instructions require it.

## Tags

Use these classifications in reports:

- `safe-cache`: developer/app cache that can be rebuilt, such as `~/go/pkg/mod`, `~/Library/Caches`, `.npm/_cacache`, `.next`, `DerivedData`.
- `review`: user/project data that may be valuable, such as `Downloads`, reports, browser profiles, app support data, and project output.
- `app-uninstall`: an app bundle in `/Applications`; delete only when the user selects uninstall/removal.
- `git-maintenance`: `.git` storage; prefer `git gc --prune=now` instead of deleting `.git`.
- `do-not-delete`: system, OS, or protected locations.

## Evidence To Return

Keep the final response concise, but include:

- final available disk space,
- selected delete count and any residual recreated-small directories,
- `git gc` repo count and failed repos,
- paths to candidate/selection/apply/final summary files,
- Feishu `message_id` if a completion card was sent.
