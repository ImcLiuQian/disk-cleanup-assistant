#!/usr/bin/env python3
"""Serve a local delete/not-delete selector for disk cleanup candidates."""

from __future__ import annotations

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


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
        rows.append(
            "<tr>"
            f"<td><input type='checkbox' aria-label='Delete {html.escape(item['id'])}' data-id='{html.escape(item['id'])}'></td>"
            f"<td class='mono'>{html.escape(item['id'])}</td>"
            f"<td class='num'>{float(item.get('size_gb', 0)):.2f}</td>"
            f"<td><span class='tag'>{html.escape(tag)}</span></td>"
            f"<td>{html.escape(item.get('recommendation', ''))}</td>"
            f"<td>{html.escape(item.get('kind', ''))}</td>"
            f"<td><code>{html.escape(item.get('path', ''))}</code></td>"
            f"<td>{html.escape(item.get('reason', ''))}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Disk Cleanup Selector</title>
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
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    header {{ margin-bottom: 18px; }}
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
    #status {{ color: var(--safe); font-weight: 600; }}
    .table-wrap {{ overflow: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 980px; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px; text-align: left; vertical-align: top; }}
    th {{ position: sticky; top: 0; background: #fbfcfe; color: #344054; font-size: 12px; text-transform: uppercase; }}
    tr:last-child td {{ border-bottom: 0; }}
    code, .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    code {{ white-space: nowrap; color: #344054; }}
    .tag {{ display: inline-block; padding: 3px 8px; border-radius: 999px; background: #eef4ff; color: #1d4ed8; font-weight: 700; white-space: nowrap; }}
    .num {{ text-align: right; }}
    .selection-path {{ max-width: 58%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Disk Cleanup Selector</h1>
      <p>Review scan candidates and save an explicit delete list before running cleanup.</p>
    </header>
    <section class="summary" aria-label="Scan summary">
      <div class="metric"><b>{len(candidates)}</b><span>Candidates</span></div>
      <div class="metric"><b>{total_gb:.2f} GiB</b><span>Total reviewed size</span></div>
      <div class="metric"><b>{html.escape(str(len(tag_counts)))}</b><span>{tag_summary or "No tags"}</span></div>
    </section>
    <div class="toolbar">
      <div class="actions">
        <button onclick="setAll(true)">Select all</button>
        <button onclick="setAll(false)">Clear</button>
        <button class="primary" onclick="save()">Save selection</button>
      </div>
      <span id="status"></span>
      <code class="selection-path">{html.escape(str(selection_path))}</code>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Delete</th><th>ID</th><th>GiB</th><th>Tag</th><th>Recommendation</th><th>Type</th><th>Path</th><th>Reason</th></tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
  </main>
  <script>
    function boxes() {{ return Array.from(document.querySelectorAll('input[type=checkbox]')); }}
    function setAll(value) {{ boxes().forEach(b => b.checked = value); }}
    async function save() {{
      const delete_ids = boxes().filter(b => b.checked).map(b => b.dataset.id);
      const res = await fetch('/save', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{ delete_ids, saved_at: new Date().toISOString() }})
      }});
      const data = await res.json();
      document.getElementById('status').textContent = `Saved ${{data.delete_ids.length}} item(s)`;
    }}
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
