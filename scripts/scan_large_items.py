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


def classify(path: Path, kind: str) -> tuple[str, str, str]:
    text = str(path)
    lowered = text.lower()
    resolved = path.resolve(strict=False)
    if any(
        resolved == protected or (protected != Path("/") and protected in resolved.parents)
        for protected in PROTECTED
    ):
        return "do-not-delete", "keep", "system or protected location"
    if "/.git" in text or text.endswith("/.git"):
        return "git-maintenance", "git-gc", "use git gc rather than deleting repository metadata"
    if text.startswith("/Applications") and text.endswith(".app"):
        return "app-uninstall", "review", "application bundle; remove only if the user selects uninstall"
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
        return "safe-cache", "delete", "cache/build artifact that can usually be rebuilt"
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
        return "review", "review", "may contain user or app data; inspect before deleting"
    if kind == "file":
        return "review", "review", "large file; user should decide"
    return "review", "review", "large directory; user should decide"


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
        "| ID | Size | Tag | Recommendation | Kind | Path | Reason |",
        "| --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for item in candidates:
        lines.append(
            f"| {item.id} | {item.size_gb:.2f} GiB | {item.tag} | {item.recommendation} | "
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
        tag, recommendation, reason = classify(path, kind)
        candidates.append(
            Candidate(
                id=f"I{index:03d}",
                kind=kind,
                path=str(path),
                size_gb=round(size_kb / 1024 / 1024, 3),
                tag=tag,
                recommendation=recommendation,
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
