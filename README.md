# Disk Cleanup Assistant

<p align="right">
  English | <a href="./README.zh-CN.md">简体中文</a>
</p>

Guided Mac disk cleanup toolkit with large-file scanning, an interactive delete selector, conservative cleanup execution, and repository maintenance with `git gc`.

Disk Cleanup Assistant is designed for the moment when "System Data" or "Documents" looks huge but it is not obvious what is safe to remove. It keeps the workflow auditable: scan first, review candidates in a local page, dry-run the saved selection, then delete only after an explicit confirmation token.

![Selector UI](./docs/images/selector-ui.svg)

## What It Provides

- Large file and directory scans with configurable roots, depth, and size threshold.
- Candidate tagging for caches, review-needed data, app bundles, git metadata, and protected paths.
- Markdown and JSON scan reports for human review and automation.
- A local browser selector with delete / keep choices.
- Dry-run cleanup logs before destructive execution.
- A hard confirmation token for deletion.
- Protected macOS path checks, including symlink targets.
- Optional `git gc --prune=now` maintenance across project folders.

## Workflow

![Cleanup workflow](./docs/images/cleanup-workflow.svg)

## Safety Model

![Safety model](./docs/images/safety-model.svg)

This toolkit is intentionally conservative.

- Scanning is read-only.
- The selector page saves choices, but does not delete anything.
- Destructive cleanup requires `--confirm-delete DELETE_SELECTED_PATHS`.
- `/`, `/System`, `/Library`, `/usr`, `/bin`, `/sbin`, and descendants or symlink targets under them are blocked.
- Personal data locations such as `Documents`, `Desktop`, `Downloads`, browser profiles, Photos libraries, Mail, and app support data should be reviewed before deletion.
- Running apps may recreate empty cache or log folders after cleanup. Verify final sizes rather than only path existence.

## Quick Start

Run the commands from the repository root.

### 1. Scan Large Candidates

```bash
python3 scripts/scan_large_items.py \
  --threshold-gb 1 \
  --depth 5 \
  --output /tmp/disk_cleanup_candidates.json \
  --markdown /tmp/disk_cleanup_candidates.md
```

Limit the scan to specific roots when needed:

```bash
python3 scripts/scan_large_items.py \
  --roots "$HOME/Library/Caches" "$HOME/my_project" "$HOME/go" \
  --threshold-gb 1 \
  --depth 5 \
  --output /tmp/disk_cleanup_candidates.json \
  --markdown /tmp/disk_cleanup_candidates.md
```

### 2. Review And Save Choices

```bash
python3 scripts/selector_server.py \
  --candidates /tmp/disk_cleanup_candidates.json \
  --selection /tmp/disk_cleanup_selection.json \
  --port 8765
```

Open:

```text
http://127.0.0.1:8765/
```

Select only the items you want to delete, then save the selection.

### 3. Dry-Run The Selection

```bash
python3 scripts/apply_selection.py \
  --candidates /tmp/disk_cleanup_candidates.json \
  --selection /tmp/disk_cleanup_selection.json \
  --log /tmp/disk_cleanup_apply_dry_run.json \
  --dry-run
```

### 4. Apply Confirmed Cleanup

```bash
python3 scripts/apply_selection.py \
  --candidates /tmp/disk_cleanup_candidates.json \
  --selection /tmp/disk_cleanup_selection.json \
  --log /tmp/disk_cleanup_apply_log.json \
  --git-gc-root "$HOME/my_project" \
  --confirm-delete DELETE_SELECTED_PATHS
```

Use `--git-gc-root` only when you want repository maintenance. Omit it for delete-only cleanup.

## Go Module Cache Note

Go tools and IDEs may rebuild or lock `~/go/pkg/mod/cache/vcs` while cleanup is running. If you intentionally selected `~/go/pkg/mod` and verified that active `go`, `git`, or `ssh` child processes are only cache rebuilders, rerun cleanup with:

```bash
python3 scripts/apply_selection.py \
  --candidates /tmp/disk_cleanup_candidates.json \
  --selection /tmp/disk_cleanup_selection.json \
  --log /tmp/disk_cleanup_apply_log.json \
  --confirm-delete DELETE_SELECTED_PATHS \
  --kill-go-cache-users
```

Use this flag narrowly. It terminates only cache-related `go`, `git`, or `ssh` child processes reported by `lsof`.

## Candidate Tags

| Tag | Meaning |
| --- | --- |
| `safe-cache` | Cache or build artifact that can usually be rebuilt. |
| `review` | User or app data that needs manual review. |
| `app-uninstall` | Application bundle; delete only when you want to uninstall it. |
| `git-maintenance` | Repository metadata; prefer `git gc` rather than deleting `.git`. |
| `do-not-delete` | System or protected location. |

## Tests

```bash
python3 -B -m unittest discover -s tests -v
```

The tests use temporary directories and dry-run paths only.

## Repository Layout

```text
.
├── LICENSE
├── README.md
├── README.zh-CN.md
├── SKILL.md
├── agents/
│   └── openai.yaml
├── docs/
│   └── images/
├── scripts/
│   ├── apply_selection.py
│   ├── scan_large_items.py
│   └── selector_server.py
└── tests/
    └── test_disk_cleanup_safety.py
```

## License

MIT.
