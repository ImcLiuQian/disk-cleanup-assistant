#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


apply_selection = load_module("apply_selection", ROOT / "scripts" / "apply_selection.py")
scan_large_items = load_module("scan_large_items", ROOT / "scripts" / "scan_large_items.py")
selector_server = load_module("selector_server", ROOT / "scripts" / "selector_server.py")


class DiskCleanupSafetyTests(unittest.TestCase):
    def test_protected_descendants_and_symlink_targets_are_blocked(self):
        for value in ["/", "/System/Library", "/Library/Developer", "/usr/local", "/bin/sh", "/sbin/mount"]:
            self.assertTrue(apply_selection.is_protected(Path(value)), value)

        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "system-link"
            link.symlink_to("/System/Library")
            self.assertTrue(apply_selection.is_protected(link))
            self.assertFalse(apply_selection.is_protected(Path(tmp) / "ordinary-cache"))

    def test_scanner_marks_protected_descendants_do_not_delete(self):
        self.assertEqual(scan_large_items.classify(Path("/System/Library"), "dir")[0], "do-not-delete")
        self.assertEqual(scan_large_items.classify(Path("/usr/local/bin/tool"), "file")[0], "do-not-delete")
        self.assertEqual(scan_large_items.classify(Path.home() / "Library" / "Caches" / "Example", "dir")[0], "safe-cache")

    def test_scanner_provides_actionable_delete_impact(self):
        cases = [
            (Path("/System/Library"), "dir"),
            (Path.home() / ".npm" / "_npx", "dir"),
            (Path.home() / "Library" / "Application Support" / "Example", "dir"),
            (Path.home() / "my_project" / "repo" / ".git", "dir"),
        ]
        for path, kind in cases:
            tag, recommendation, _reason, impact = scan_large_items.classify(path, kind)
            self.assertIn(tag, {"safe-cache", "review", "git-maintenance", "do-not-delete"})
            self.assertIn(recommendation, {"delete", "review", "git-gc", "keep"})
            self.assertTrue(impact.strip(), path)

    def test_selector_has_impact_fallback_for_legacy_scan_and_escapes_new_impact(self):
        label_zh, label_en, legacy_impact_zh, legacy_impact_en, style = selector_server.deletion_guidance(
            {"tag": "git-maintenance", "recommendation": "git-gc"}
        )
        self.assertEqual(label_zh, "不要直接删")
        self.assertEqual(label_en, "Do not delete directly")
        self.assertIn("git gc", legacy_impact_zh)
        self.assertIn("git gc", legacy_impact_en)
        self.assertEqual(style, "danger")

        npx_label_zh, npx_label_en, npx_impact_zh, npx_impact_en, npx_style = selector_server.deletion_guidance(
            {
                "tag": "review",
                "recommendation": "review",
                "path": str(Path.home() / ".npm" / "_npx"),
            }
        )
        self.assertEqual(npx_label_zh, "建议删")
        self.assertEqual(npx_label_en, "Recommended")
        self.assertTrue(npx_impact_zh)
        self.assertTrue(npx_impact_en)
        self.assertEqual(npx_style, "recommended")

        rendered = selector_server.render_html(
            [
                {
                    "id": "I001",
                    "size_gb": 1,
                    "tag": "safe-cache",
                    "recommendation": "delete",
                    "impact": "重建 <缓存>",
                    "impact_en": "rebuild <cache>",
                    "kind": "dir",
                    "path": "/tmp/cache",
                    "reason": "test",
                }
            ],
            Path("/tmp/selection.json"),
        )
        self.assertIn('<body data-language="zh">', rendered)
        self.assertIn('id="language-toggle"', rendered)
        self.assertIn("let language = 'zh'", rendered)
        self.assertIn("重建 &lt;缓存&gt;", rendered)
        self.assertIn("rebuild &lt;cache&gt;", rendered)
        self.assertNotIn("重建 <缓存>", rendered)
        self.assertNotIn("rebuild <cache>", rendered)

    def test_apply_requires_confirmation_for_destructive_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            (target / "file.txt").write_text("x", encoding="utf-8")
            candidates = root / "candidates.json"
            selection = root / "selection.json"
            log = root / "apply.json"
            candidates.write_text(
                json.dumps({"candidates": [{"id": "I001", "path": str(target)}]}),
                encoding="utf-8",
            )
            selection.write_text(json.dumps({"delete_ids": ["I001"]}), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "scripts" / "apply_selection.py"),
                    "--candidates",
                    str(candidates),
                    "--selection",
                    str(selection),
                    "--log",
                    str(log),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertTrue(target.exists())
            self.assertEqual(json.loads(log.read_text(encoding="utf-8"))["status"], "blocked")

    def test_apply_dry_run_and_confirmed_temp_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            (target / "file.txt").write_text("x", encoding="utf-8")
            candidates = root / "candidates.json"
            selection = root / "selection.json"
            dry_log = root / "dry.json"
            delete_log = root / "delete.json"
            candidates.write_text(
                json.dumps({"candidates": [{"id": "I001", "path": str(target)}]}),
                encoding="utf-8",
            )
            selection.write_text(json.dumps({"delete_ids": ["I001"]}), encoding="utf-8")

            dry = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "scripts" / "apply_selection.py"),
                    "--candidates",
                    str(candidates),
                    "--selection",
                    str(selection),
                    "--log",
                    str(dry_log),
                    "--dry-run",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(dry.returncode, 0)
            self.assertTrue(target.exists())

            delete = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "scripts" / "apply_selection.py"),
                    "--candidates",
                    str(candidates),
                    "--selection",
                    str(selection),
                    "--log",
                    str(delete_log),
                    "--confirm-delete",
                    apply_selection.CONFIRM_DELETE_TOKEN,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(delete.returncode, 0, delete.stdout + delete.stderr)
            self.assertFalse(target.exists())
            summary = json.loads(delete.stdout)
            self.assertEqual(summary["attempted_delete_count"], 1)
            self.assertEqual(summary["deleted_count"], 1)

    def test_selection_collapse_and_selector_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "parent"
            child = parent / "child"
            child.mkdir(parents=True)
            targets, covered = apply_selection.collapse_selected([("P", parent), ("C", child)])
            self.assertEqual(targets, [("P", parent)])
            self.assertEqual(covered, {"C": "P"})

            selection = root / "selection.json"
            saved = selector_server.save_selection(
                [{"id": "P"}, {"id": "C"}],
                selection,
                {"delete_ids": ["P", "BAD"], "saved_at": "now"},
            )
            self.assertEqual(saved["delete_ids"], ["P"])
            self.assertEqual(json.loads(selection.read_text(encoding="utf-8"))["delete_ids"], ["P"])


if __name__ == "__main__":
    unittest.main()
