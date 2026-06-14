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
    rows = []
    for item in candidates:
        rows.append(
            "<tr>"
            f"<td><input type='checkbox' data-id='{html.escape(item['id'])}'></td>"
            f"<td>{html.escape(item['id'])}</td>"
            f"<td class='num'>{float(item.get('size_gb', 0)):.2f}</td>"
            f"<td>{html.escape(item.get('tag', ''))}</td>"
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
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 24px; color: #17202a; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #d8dee4; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ position: sticky; top: 0; background: white; }}
    code {{ white-space: nowrap; }}
    .num {{ text-align: right; }}
    .bar {{ display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }}
    button {{ padding: 7px 12px; border: 1px solid #9aa4b2; background: #f6f8fa; border-radius: 6px; cursor: pointer; }}
    #status {{ color: #226d2c; }}
  </style>
</head>
<body>
  <h1>Disk Cleanup Selector</h1>
  <div class="bar">
    <button onclick="setAll(true)">全选</button>
    <button onclick="setAll(false)">全不选</button>
    <button onclick="save()">保存选择</button>
    <span id="status"></span>
  </div>
  <p>保存位置：<code>{html.escape(str(selection_path))}</code></p>
  <table>
    <thead>
      <tr><th>删</th><th>ID</th><th>GiB</th><th>Tag</th><th>建议</th><th>类型</th><th>路径</th><th>原因</th></tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
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
      document.getElementById('status').textContent = `已保存 ${{data.delete_ids.length}} 项`;
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
