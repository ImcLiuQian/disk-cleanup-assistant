#!/usr/bin/env python3
"""Read-only scanner for large Mac disk cleanup candidates."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path


HOME = Path.home()
PROTECTED = {Path("/"), Path("/System"), Path("/Library"), Path("/usr"), Path("/bin"), Path("/sbin")}
DEFAULT_ROOTS = [
    HOME / "Library" / "Caches",
    HOME / "Library" / "Application Support",
    HOME / "Downloads",
    HOME / "Documents",
    HOME / "Desktop",
    HOME / "go",
    HOME / ".npm",
    HOME / "my_project",
    Path("/Applications"),
]


@dataclass
class Candidate:
    id: str
    kind: str
    path: str
    size_gb: float
    tag: str
    recommendation: str
    impact: str
    reason: str


def run_du(root: Path, depth: int) -> list[tuple[int, Path]]:
    if not root.exists():
        return []
    result = subprocess.run(
        ["du", "-x", "-k", "-d", str(depth), str(root)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    rows: list[tuple[int, Path]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        size, path = line.split(None, 1)
        rows.append((int(size), Path(path)))
    return rows


def iter_large_files(root: Path, threshold_kb: int, max_depth: int) -> list[tuple[int, Path]]:
    if not root.exists() or not root.is_dir():
        return []
    rows: list[tuple[int, Path]] = []
    root_parts = len(root.parts)
    try:
        root_dev = root.stat().st_dev
    except OSError:
        root_dev = None
    for current, dirs, files in os.walk(root):
        cur = Path(current)
        if len(cur.parts) - root_parts >= max_depth:
            dirs[:] = []
        if root_dev is not None:
            kept = []
            for name in dirs:
                try:
                    if (cur / name).stat().st_dev == root_dev:
                        kept.append(name)
                except OSError:
                    pass
            dirs[:] = kept
        for name in files:
            path = cur / name
            try:
                size_kb = path.stat().st_size // 1024
            except OSError:
                continue
            if size_kb >= threshold_kb:
                rows.append((size_kb, path))
    return rows


def classify(path: Path, kind: str) -> tuple[str, str, str, str]:
    text = str(path)
    lowered = text.lower()
    resolved = path.resolve(strict=False)
    if any(
        resolved == protected or (protected != Path("/") and protected in resolved.parents)
        for protected in PROTECTED
    ):
        return (
            "do-not-delete",
            "keep",
            "system or protected location",
            "可能破坏 macOS 或关键工具；清理脚本也会阻止删除。",
        )
    if "/.git" in text or text.endswith("/.git"):
        return (
            "git-maintenance",
            "git-gc",
            "use git gc rather than deleting repository metadata",
            "直接删除会破坏仓库历史、分支和 Git 状态；应改用 git gc。",
        )
    if text.startswith("/Applications") and text.endswith(".app"):
        return (
            "app-uninstall",
            "review",
            "application bundle; remove only if the user selects uninstall",
            "应用本体将无法启动；Library 下的设置和用户数据通常仍会保留。",
        )
    if "/.npm/_npx" in text:
        return (
            "safe-cache",
            "delete",
            "downloaded npx package cache that can be rebuilt",
            "已下载的 npx 临时包会被清除；下次运行 npx 时会重新下载。",
        )
    if "chrome" in lowered and "/service worker/cachestorage" in lowered:
        return (
            "review",
            "review",
            "browser site cache inside a profile; close the browser and review before deleting",
            "网站和 PWA 会重建缓存，离线数据可能丢失；Cookie、历史记录和书签通常不受影响。",
        )
    cache_markers = [
        "/Library/Caches",
        "/.npm/_cacache",
        "/go/pkg/mod",
        "/.cache",
        "/DerivedData",
        "/.next",
        "/node_modules",
    ]
    if any(marker in text for marker in cache_markers):
        if "/JetBrains/" in text:
            impact = "IDE 索引和缓存会重建；下次启动可能较慢，并会暂时占用更多 CPU。"
        elif "org.sparkle-project.Sparkle" in text:
            impact = "已下载的更新包会被清除，应用可能重新下载；更新进行中不要删除。"
        elif "/.npm/_cacache" in text:
            impact = "npm 包缓存会被清除；后续安装会重新下载，但项目文件不受影响。"
        elif "/go/pkg/mod" in text:
            impact = "已下载的 Go Modules 会被清除；后续构建会重新下载，首次构建更慢。"
        elif "/node_modules" in text:
            impact = "已安装依赖会被清除；再次构建或运行项目前需要重新安装依赖。"
        else:
            impact = "通常不影响个人数据；应用或工具会重建或重新下载缓存，首次启动或构建可能变慢。"
        return "safe-cache", "delete", "cache/build artifact that can usually be rebuilt", impact
    if text.startswith(str(HOME / "my_project")):
        return (
            "review",
            "review",
            "project directory; verify repository state and generated-output boundaries",
            "可能永久删除源码、未提交修改、Git 元数据和构建产物；只应删除已确认无用的子目录。",
        )
    review_markers = [
        "/Downloads",
        "/Documents",
        "/Desktop",
        "/Library/Application Support",
        "photos library",
        "chrome",
        "larkshell",
        "report",
        "output",
    ]
    if any(marker.lower() in lowered for marker in review_markers):
        if "/library/application support" in lowered:
            impact = "可能清除应用设置、会话、离线数据或本地运行文件，并导致重新登录或下载。"
        elif any(marker in lowered for marker in ["/downloads", "/documents", "/desktop"]):
            impact = "这里可能是个人文件；若无其他备份，删除后会永久丢失。"
        else:
            impact = "可能包含用户、项目或应用数据；删除前先检查内容与备份。"
        return "review", "review", "may contain user or app data; inspect before deleting", impact
    if kind == "file":
        return (
            "review",
            "review",
            "large file; user should decide",
            "文件会被永久删除；先确认内容、来源和备份。",
        )
    return (
        "review",
        "review",
        "large directory; user should decide",
        "目录及全部内容会被永久删除；勾选前先检查。",
    )


def unique_rows(rows: list[tuple[int, Path, str]]) -> list[tuple[int, Path, str]]:
    seen: set[str] = set()
    out = []
    for size, path, kind in rows:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append((size, path, kind))
    return out


def write_markdown(candidates: list[Candidate], path: Path) -> None:
    lines = [
        "# Disk Cleanup Candidates",
        "",
        "| ID | Size | Tag | Recommendation | Impact if deleted | Kind | Path | Reason |",
        "| --- | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for item in candidates:
        lines.append(
            f"| {item.id} | {item.size_gb:.2f} GiB | {item.tag} | {item.recommendation} | {item.impact} | "
            f"{item.kind} | `{item.path}` | {item.reason} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roots", nargs="*", type=Path, default=DEFAULT_ROOTS)
    parser.add_argument("--threshold-gb", type=float, default=1.0)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    threshold_kb = int(args.threshold_gb * 1024 * 1024)
    rows: list[tuple[int, Path, str]] = []
    for root in args.roots:
        rows.extend((size, path, "dir") for size, path in run_du(root, args.depth) if size >= threshold_kb)
        rows.extend((size, path, "file") for size, path in iter_large_files(root, threshold_kb, args.depth))
    rows = sorted(unique_rows(rows), key=lambda x: x[0], reverse=True)

    candidates: list[Candidate] = []
    for index, (size_kb, path, kind) in enumerate(rows, 1):
        tag, recommendation, reason, impact = classify(path, kind)
        candidates.append(
            Candidate(
                id=f"I{index:03d}",
                kind=kind,
                path=str(path),
                size_gb=round(size_kb / 1024 / 1024, 3),
                tag=tag,
                recommendation=recommendation,
                impact=impact,
                reason=reason,
            )
        )

    payload = {
        "threshold_gb": args.threshold_gb,
        "roots": [str(p) for p in args.roots],
        "count": len(candidates),
        "candidates": [asdict(item) for item in candidates],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        write_markdown(candidates, args.markdown)
    print(json.dumps({"count": len(candidates), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
