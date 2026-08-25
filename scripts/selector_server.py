#!/usr/bin/env python3
"""Serve a local delete/not-delete selector for disk cleanup candidates."""

from __future__ import annotations

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


RECOMMENDATION_LABELS = {
    "delete": ("建议删", "Recommended"),
    "review": ("确认后再删", "Review first"),
    "git-gc": ("不要直接删", "Do not delete directly"),
    "keep": ("不要删", "Keep"),
}

RECOMMENDATION_STYLES = {
    "delete": "recommended",
    "review": "caution",
    "git-gc": "danger",
    "keep": "danger",
}

LEGACY_IMPACTS_ZH = {
    "safe-cache": "通常不影响个人数据；应用或工具会重建或重新下载缓存，首次启动、索引或构建可能变慢。",
    "review": "可能包含用户、项目或应用数据；删除后可能丢失设置、登录状态、离线数据或未备份文件。",
    "app-uninstall": "应用本体将无法启动；Library 下的设置和用户数据可能仍会保留。",
    "git-maintenance": "直接删除可能破坏仓库历史、分支和 Git 状态；应改用 git gc。",
    "do-not-delete": "可能破坏 macOS 或关键工具；清理脚本也会阻止删除。",
}


LEGACY_IMPACTS_EN = {
    "safe-cache": "Personal data is normally unaffected. The app or tool will rebuild or download the cache again, so the next launch, index, or build may be slower.",
    "review": "This may contain user, project, or app data. Deletion can remove settings, sign-in state, offline data, or files without backups.",
    "app-uninstall": "The application will no longer launch. Settings and user data under Library may remain.",
    "git-maintenance": "Direct deletion can destroy repository history, branches, and Git state. Use git gc instead.",
    "do-not-delete": "This may break macOS or a critical tool. The cleanup runner also blocks the path.",
}


REASON_ZH = {
    "system or protected location": "系统或受保护路径",
    "use git gc rather than deleting repository metadata": "仓库元数据不能直接删除，应使用 git gc",
    "application bundle; remove only if the user selects uninstall": "应用程序包；仅在确认卸载时删除",
    "downloaded npx package cache that can be rebuilt": "可重新下载的 npx 包缓存",
    "browser site cache inside a profile; close the browser and review before deleting": "浏览器 Profile 内的网站缓存；退出浏览器后再确认",
    "cache/build artifact that can usually be rebuilt": "通常可以重建的缓存或构建产物",
    "project directory; verify repository state and generated-output boundaries": "项目目录；先核对仓库状态和生成产物边界",
    "may contain user or app data; inspect before deleting": "可能包含用户或应用数据；删除前检查",
    "large file; user should decide": "大文件；需要人工判断",
    "large directory; user should decide": "大目录；需要人工判断",
}


def inferred_impacts(item: dict) -> tuple[str | None, str, str]:
    tag = str(item.get("tag", ""))
    path = str(item.get("path", ""))
    lowered = path.lower()
    kind = str(item.get("kind", ""))

    if tag in {"git-maintenance", "do-not-delete", "app-uninstall"}:
        return None, LEGACY_IMPACTS_ZH[tag], LEGACY_IMPACTS_EN[tag]
    if "/.npm/_npx" in path:
        return (
            "delete",
            "已下载的 npx 临时包会被清除；下次运行 npx 时会重新下载。",
            "Downloaded npx packages are removed. The next npx run will download them again.",
        )
    if "chrome" in lowered and "/service worker/cachestorage" in lowered:
        return (
            None,
            "网站和 PWA 会重建缓存，离线数据可能丢失；Cookie、历史记录和书签通常不受影响。",
            "Sites and PWAs will rebuild cached resources, and offline data may be lost. Cookies, history, and bookmarks are normally unaffected.",
        )
    if "/library/caches/jetbrains" in lowered:
        return (
            None,
            "IDE 索引和缓存会重建；下次启动可能较慢，并会暂时占用更多 CPU。",
            "IDE indexes and caches will rebuild. The next launch may be slower and temporarily use more CPU.",
        )
    if "org.sparkle-project.sparkle" in lowered:
        return (
            None,
            "已下载的更新包会被清除，应用可能重新下载；更新进行中不要删除。",
            "Downloaded updater packages are removed, and the app may download them again. Do not delete during an active update.",
        )
    if "/.npm/_cacache" in path:
        return (
            None,
            "npm 包缓存会被清除；后续安装会重新下载，但项目文件不受影响。",
            "The npm package cache is removed. Later installs may download packages again, but project files are unaffected.",
        )
    if "/go/pkg/mod" in path:
        return (
            None,
            "已下载的 Go Modules 会被清除；后续构建会重新下载，首次构建更慢。",
            "Downloaded Go modules are removed. Later builds will download them again, making the first build slower.",
        )
    if "/node_modules" in path:
        return (
            None,
            "已安装依赖会被清除；再次构建或运行项目前需要重新安装依赖。",
            "Installed dependencies are removed. Reinstall them before building or running the project again.",
        )
    if "/library/application support" in lowered:
        return (
            None,
            "可能清除应用设置、会话、离线数据或本地运行文件，并导致重新登录或下载。",
            "This may clear app settings, sessions, offline data, or local runtime files and require sign-in or downloads again.",
        )
    if "/my_project" in path:
        return (
            None,
            "可能永久删除源码、未提交修改、Git 元数据和构建产物；只应删除已确认无用的子目录。",
            "This may permanently remove source code, uncommitted work, Git metadata, and build outputs. Delete only a confirmed disposable child directory.",
        )
    if any(marker in lowered for marker in ["/downloads", "/documents", "/desktop"]):
        return (
            None,
            "这里可能是个人文件；若无其他备份，删除后会永久丢失。",
            "This location may contain personal files. Without another backup, deletion is permanent.",
        )
    if tag in LEGACY_IMPACTS_ZH:
        return None, LEGACY_IMPACTS_ZH[tag], LEGACY_IMPACTS_EN[tag]
    if kind == "file":
        return (
            None,
            "文件会被永久删除；先确认内容、来源和备份。",
            "The file is permanently removed. Verify its contents, source, and backup first.",
        )
    return (
        None,
        "目录及全部内容会被永久删除；勾选前先检查。",
        "The directory and all of its contents are permanently removed. Inspect it before selecting delete.",
    )


def deletion_guidance(item: dict) -> tuple[str, str, str, str, str]:
    recommendation = str(item.get("recommendation", ""))
    inferred_recommendation, inferred_zh, inferred_en = inferred_impacts(item)
    if inferred_recommendation:
        recommendation = inferred_recommendation
    label_zh, label_en = RECOMMENDATION_LABELS.get(recommendation, ("需判断", "Review"))
    style = RECOMMENDATION_STYLES.get(recommendation, "caution")
    impact_zh = str(item.get("impact") or inferred_zh)
    impact_en = str(item.get("impact_en") or inferred_en)
    return label_zh, label_en, impact_zh, impact_en, style


def localized_reason(item: dict) -> tuple[str, str]:
    reason_en = str(item.get("reason") or "Review required")
    reason_zh = str(item.get("reason_zh") or REASON_ZH.get(reason_en) or "需要人工检查")
    return reason_zh, reason_en


def load_candidates(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("candidates", data if isinstance(data, list) else [])


def render_html(candidates: list[dict], selection_path: Path) -> str:
    total_gb = sum(float(item.get("size_gb", 0)) for item in candidates)
    tag_counts: dict[str, int] = {}
    for item in candidates:
        tag = item.get("tag", "untagged")
        tag_counts[tag] = tag_counts.get(tag, 0) + 1

    tag_summary = " · ".join(f"{html.escape(tag)} {count}" for tag, count in sorted(tag_counts.items()))
    rows = []
    for item in candidates:
        tag = item.get("tag", "")
        label_zh, label_en, impact_zh, impact_en, recommendation_style = deletion_guidance(item)
        reason_zh, reason_en = localized_reason(item)
        kind = str(item.get("kind", ""))
        kind_zh = {"dir": "目录", "file": "文件"}.get(kind, kind)
        rows.append(
            "<tr>"
            f"<td><input type='checkbox' aria-label='删除 {html.escape(item['id'])}' data-id='{html.escape(item['id'])}'></td>"
            f"<td class='mono'>{html.escape(item['id'])}</td>"
            f"<td class='num'>{float(item.get('size_gb', 0)):.2f}</td>"
            f"<td><span class='tag'>{html.escape(tag)}</span></td>"
            f"<td><span class='recommendation {recommendation_style}'>"
            f"<span class='lang-zh' lang='zh-CN'>{html.escape(label_zh)}</span>"
            f"<span class='lang-en' lang='en'>{html.escape(label_en)}</span>"
            "</span></td>"
            f"<td class='impact localized-block'>"
            f"<span class='lang-zh' lang='zh-CN'>{html.escape(impact_zh)}</span>"
            f"<span class='lang-en' lang='en'>{html.escape(impact_en)}</span>"
            "</td>"
            f"<td><span class='lang-zh' lang='zh-CN'>{html.escape(kind_zh)}</span>"
            f"<span class='lang-en' lang='en'>{html.escape(kind)}</span></td>"
            f"<td><code>{html.escape(item.get('path', ''))}</code></td>"
            f"<td class='reason localized-block'>"
            f"<span class='lang-zh' lang='zh-CN'>{html.escape(reason_zh)}</span>"
            f"<span class='lang-en' lang='en'>{html.escape(reason_en)}</span>"
            "</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>磁盘清理选择器</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --line: #d9e0ea;
      --text: #182230;
      --muted: #667085;
      --accent: #2563eb;
      --accent-dark: #1d4ed8;
      --safe: #0f766e;
      --warning: #b54708;
      --danger: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    body[data-language="zh"] .lang-en,
    body[data-language="en"] .lang-zh {{ display: none; }}
    body[data-language="zh"] .lang-zh,
    body[data-language="en"] .lang-en {{ display: inline; }}
    body[data-language="zh"] .localized-block > .lang-zh,
    body[data-language="en"] .localized-block > .lang-en {{ display: block; }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 28px; }}
    header {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 18px; }}
    .page-heading {{ min-width: 0; }}
    h1 {{ margin: 0 0 6px; font-size: 30px; letter-spacing: 0; }}
    p {{ color: var(--muted); margin: 0; }}
    .summary {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }}
    .metric {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .metric b {{ display: block; font-size: 22px; margin-bottom: 3px; }}
    .metric span {{ color: var(--muted); font-size: 13px; }}
    .toolbar {{
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 14px;
    }}
    .actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    button {{
      padding: 8px 12px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 6px;
      cursor: pointer;
      font-weight: 600;
    }}
    button.primary {{ background: var(--accent); border-color: var(--accent); color: white; }}
    button.primary:hover {{ background: var(--accent-dark); }}
    button.language-toggle {{ flex: 0 0 auto; min-width: 82px; border-color: #b2ccff; color: var(--accent-dark); }}
    #status {{ color: var(--safe); font-weight: 600; }}
    .table-wrap {{ overflow: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 1260px; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px; text-align: left; vertical-align: top; }}
    th {{ position: sticky; top: 0; background: #fbfcfe; color: #344054; font-size: 12px; text-transform: uppercase; }}
    tr:last-child td {{ border-bottom: 0; }}
    code, .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    code {{ white-space: nowrap; color: #344054; }}
    .tag {{ display: inline-block; padding: 3px 8px; border-radius: 999px; background: #eef4ff; color: #1d4ed8; font-weight: 700; white-space: nowrap; }}
    .recommendation {{ display: inline-block; padding: 3px 8px; border-radius: 999px; font-weight: 700; white-space: nowrap; }}
    .recommendation.recommended {{ background: #ecfdf3; color: var(--safe); }}
    .recommendation.caution {{ background: #fffaeb; color: var(--warning); }}
    .recommendation.danger {{ background: #fef3f2; color: var(--danger); }}
    .impact {{ min-width: 260px; max-width: 360px; color: #475467; line-height: 1.45; }}
    .reason {{ min-width: 190px; max-width: 280px; color: #475467; line-height: 1.45; }}
    .num {{ text-align: right; }}
    .selection-path {{ max-width: 58%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  </style>
</head>
<body data-language="zh">
  <main>
    <header>
      <div class="page-heading">
        <h1><span class="lang-zh" lang="zh-CN">磁盘清理选择器</span><span class="lang-en" lang="en">Disk Cleanup Selector</span></h1>
        <p><span class="lang-zh" lang="zh-CN">逐项检查扫描结果，保存明确的删除清单后再执行清理。</span><span class="lang-en" lang="en">Review scan candidates and save an explicit delete list before running cleanup.</span></p>
      </div>
      <button id="language-toggle" class="language-toggle" type="button" onclick="toggleLanguage()" aria-label="Switch to English">English</button>
    </header>
    <section id="scan-summary" class="summary" aria-label="扫描摘要">
      <div class="metric"><b>{len(candidates)}</b><span><span class="lang-zh" lang="zh-CN">候选项</span><span class="lang-en" lang="en">Candidates</span></span></div>
      <div class="metric"><b>{total_gb:.2f} GiB</b><span><span class="lang-zh" lang="zh-CN">候选项累计大小</span><span class="lang-en" lang="en">Total reviewed size</span></span></div>
      <div class="metric"><b>{html.escape(str(len(tag_counts)))}</b><span>{tag_summary or "No tags"}</span></div>
    </section>
    <div class="toolbar">
      <div class="actions">
        <button onclick="setAll(true)"><span class="lang-zh" lang="zh-CN">全选</span><span class="lang-en" lang="en">Select all</span></button>
        <button onclick="setAll(false)"><span class="lang-zh" lang="zh-CN">清空</span><span class="lang-en" lang="en">Clear</span></button>
        <button class="primary" onclick="save()"><span class="lang-zh" lang="zh-CN">保存选择</span><span class="lang-en" lang="en">Save selection</span></button>
      </div>
      <span id="status"></span>
      <code class="selection-path">{html.escape(str(selection_path))}</code>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th><span class="lang-zh" lang="zh-CN">删除</span><span class="lang-en" lang="en">Delete</span></th>
            <th><span class="lang-zh" lang="zh-CN">编号</span><span class="lang-en" lang="en">ID</span></th>
            <th>GiB</th>
            <th><span class="lang-zh" lang="zh-CN">标签</span><span class="lang-en" lang="en">Tag</span></th>
            <th><span class="lang-zh" lang="zh-CN">建议删除?</span><span class="lang-en" lang="en">Delete?</span></th>
            <th><span class="lang-zh" lang="zh-CN">删除影响</span><span class="lang-en" lang="en">Impact if deleted</span></th>
            <th><span class="lang-zh" lang="zh-CN">类型</span><span class="lang-en" lang="en">Type</span></th>
            <th><span class="lang-zh" lang="zh-CN">路径</span><span class="lang-en" lang="en">Path</span></th>
            <th><span class="lang-zh" lang="zh-CN">分类依据</span><span class="lang-en" lang="en">Reason</span></th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
  </main>
  <script>
    let language = 'zh';
    function boxes() {{ return Array.from(document.querySelectorAll('input[type=checkbox]')); }}
    function setAll(value) {{ boxes().forEach(b => b.checked = value); }}
    function applyLanguage() {{
      document.body.dataset.language = language;
      document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
      document.title = language === 'zh' ? '磁盘清理选择器' : 'Disk Cleanup Selector';
      const toggle = document.getElementById('language-toggle');
      toggle.textContent = language === 'zh' ? 'English' : '中文';
      toggle.setAttribute('aria-label', language === 'zh' ? 'Switch to English' : '切换到中文');
      document.getElementById('scan-summary').setAttribute('aria-label', language === 'zh' ? '扫描摘要' : 'Scan summary');
      boxes().forEach(b => b.setAttribute('aria-label', `${{language === 'zh' ? '删除' : 'Delete'}} ${{b.dataset.id}}`));
    }}
    function toggleLanguage() {{
      language = language === 'zh' ? 'en' : 'zh';
      applyLanguage();
    }}
    async function save() {{
      const delete_ids = boxes().filter(b => b.checked).map(b => b.dataset.id);
      const res = await fetch('/save', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{ delete_ids, saved_at: new Date().toISOString() }})
      }});
      const data = await res.json();
      document.getElementById('status').textContent = language === 'zh'
        ? `已保存 ${{data.delete_ids.length}} 项`
        : `Saved ${{data.delete_ids.length}} item(s)`;
    }}
    applyLanguage();
  </script>
</body>
</html>"""


def save_selection(candidates: list[dict], selection_path: Path, payload: dict) -> dict:
    valid = {item["id"] for item in candidates}
    delete_ids = [item_id for item_id in payload.get("delete_ids", []) if item_id in valid]
    saved = {"delete_ids": delete_ids, "saved_at": payload.get("saved_at")}
    selection_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return saved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--render-only", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidates = load_candidates(args.candidates)
    if args.render_only:
        args.render_only.write_text(render_html(candidates, args.selection), encoding="utf-8")
        print(json.dumps({"rendered": str(args.render_only), "count": len(candidates)}, ensure_ascii=False))
        return 0

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = render_html(candidates, args.selection).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path != "/save":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            saved = save_selection(candidates, args.selection, payload)
            body = json.dumps(saved, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"http://127.0.0.1:{args.port}/")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
