# Disk Cleanup Assistant

Guided Mac disk cleanup toolkit with large-file scanning, interactive delete selection, safe cleanup execution, and `git gc` maintenance.

Disk Cleanup Assistant helps you inspect local disk usage before deleting anything. It scans large files and directories, classifies cleanup candidates, serves a local selection page, applies only explicitly confirmed deletion choices, and can run `git gc` across project folders to reduce repository storage.

## Features

- Scan large directories and files over a configurable threshold.
- Classify candidates as cache, review-needed data, app uninstall, git maintenance, or protected paths.
- Generate a Markdown report and JSON candidate list.
- Serve a local delete/not-delete selector.
- Require an explicit confirmation token before destructive cleanup.
- Block protected macOS paths and symlink targets under system locations.
- Optionally run `git gc --prune=now` across project repositories.
- Keep machine-readable logs for audit and rollback reasoning.

## Safety Model

This toolkit is intentionally conservative.

- Scanning is read-only.
- The selector page saves choices, but does not delete anything.
- Destructive cleanup requires `--confirm-delete DELETE_SELECTED_PATHS`.
- `/`, `/System`, `/Library`, `/usr`, `/bin`, `/sbin`, and descendants or symlink targets under them are blocked.
- Personal data locations such as `Documents`, `Desktop`, `Downloads`, browser profiles, Photos libraries, Mail, and app support data should be reviewed before deletion.
- Running apps may recreate empty cache or log folders after cleanup. Verify final sizes rather than only path existence.

## Quick Start

Run the commands from the repository root.

### 1. Scan large candidates

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

### 2. Review and save delete choices

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

Select only the items you want to delete, then click save.

### 3. Dry-run the saved selection

```bash
python3 scripts/apply_selection.py \
  --candidates /tmp/disk_cleanup_candidates.json \
  --selection /tmp/disk_cleanup_selection.json \
  --log /tmp/disk_cleanup_apply_dry_run.json \
  --dry-run
```

### 4. Apply confirmed cleanup

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
├── SKILL.md
├── agents/
│   └── openai.yaml
├── scripts/
│   ├── apply_selection.py
│   ├── scan_large_items.py
│   └── selector_server.py
└── tests/
    └── test_disk_cleanup_safety.py
```

## License

MIT.

---

# Disk Cleanup Assistant 中文说明

Disk Cleanup Assistant 是一个通用的 Mac 磁盘清理工具集，支持大文件/大目录扫描、交互式删除选择、安全执行清理，以及对项目目录执行 `git gc`。

它的核心原则是：先扫描、再选择、最后显式确认后才删除。扫描和选择不会删除任何文件；真正执行删除时必须传入确认 token。

## 功能

- 扫描超过阈值的大目录和大文件。
- 自动给候选项打标签：缓存、需人工确认的数据、应用卸载、git 维护、系统保护路径。
- 输出 Markdown 报告和 JSON 候选列表。
- 启动本地网页，用于勾选“删/不删”。
- 删除前强制要求 `--confirm-delete DELETE_SELECTED_PATHS`。
- 阻止删除 macOS 系统路径，以及指向系统路径的符号链接。
- 可选对项目目录批量执行 `git gc --prune=now`。
- 输出 JSON 日志，方便审计和复盘。

## 安全机制

- 扫描只读。
- 选择页面只保存选择，不执行删除。
- 未传确认 token 时，清理脚本会直接阻断。
- `/`、`/System`、`/Library`、`/usr`、`/bin`、`/sbin` 及其子路径会被保护。
- `Documents`、`Desktop`、`Downloads`、浏览器 profile、照片库、邮件、应用数据等默认需要人工确认。
- 运行中的应用可能会重建空的缓存/日志目录，因此最终判断应看目录大小而不是只看路径是否存在。

## 快速开始

### 1. 扫描

```bash
python3 scripts/scan_large_items.py \
  --threshold-gb 1 \
  --depth 5 \
  --output /tmp/disk_cleanup_candidates.json \
  --markdown /tmp/disk_cleanup_candidates.md
```

### 2. 打开选择页面

```bash
python3 scripts/selector_server.py \
  --candidates /tmp/disk_cleanup_candidates.json \
  --selection /tmp/disk_cleanup_selection.json \
  --port 8765
```

然后打开：

```text
http://127.0.0.1:8765/
```

### 3. 先 dry-run

```bash
python3 scripts/apply_selection.py \
  --candidates /tmp/disk_cleanup_candidates.json \
  --selection /tmp/disk_cleanup_selection.json \
  --log /tmp/disk_cleanup_apply_dry_run.json \
  --dry-run
```

### 4. 确认执行

```bash
python3 scripts/apply_selection.py \
  --candidates /tmp/disk_cleanup_candidates.json \
  --selection /tmp/disk_cleanup_selection.json \
  --log /tmp/disk_cleanup_apply_log.json \
  --git-gc-root "$HOME/my_project" \
  --confirm-delete DELETE_SELECTED_PATHS
```

## 测试

```bash
python3 -B -m unittest discover -s tests -v
```

## License

MIT.
