import tempfile
import unittest
from pathlib import Path

from project_reader import collect_files, scan_project


class ProjectReaderTests(unittest.TestCase):
    def test_credentials_and_generated_files_are_excluded(self):
        snapshot = collect_files([
            (".env", b"PASSWORD=private"),
            ("credentials.json", b'{"private_key": "private"}'),
            ("node_modules/dependency/index.js", b"module.exports = 1;"),
            ("README.md", b"A useful project."),
        ])
        self.assertEqual([f.path for f in snapshot.files], ["README.md"])
        self.assertEqual(len(snapshot.skipped), 3)

    def test_redaction_preserves_source_line_numbers(self):
        snapshot = collect_files([("app.py", b'print("start")\nAPI_KEY = "example-secret"\nprint("done")\n')])
        source = snapshot.files[0]
        self.assertNotIn("example-secret", source.text)
        self.assertEqual(source.redacted_lines, (2,))
        self.assertIn('3: print("done")', source.numbered_text())

    def test_paths_cannot_escape_the_project(self):
        snapshot = collect_files([(name, b"data") for name in
                                 ["../outside.py", "/absolute.py", "C:\\private.py", "src/../private.py"]])
        self.assertEqual(snapshot.files, [])
        self.assertEqual(len(snapshot.skipped), 4)

    def test_duplicate_normalized_paths_are_excluded(self):
        snapshot = collect_files([("src\\app.py", b"first"), ("src/app.py", b"second")])
        self.assertEqual(len(snapshot.files), 1)
        self.assertEqual(snapshot.skipped[0]["reason"], "duplicate path")

    def test_binary_and_non_utf8_content_is_excluded(self):
        snapshot = collect_files([("binary.py", b"hello\x00there"), ("encoded.txt", b"\xff\xfe")])
        self.assertEqual(snapshot.files, [])
        self.assertEqual(len(snapshot.skipped), 2)

    def test_file_count_and_size_budgets(self):
        snapshot = collect_files([("large.py", b"x" * 11), ("a.py", b"first"),
                                  ("b.py", b"second"), ("c.py", b"third")],
                                 max_files=1, max_file_bytes=10)
        self.assertEqual([f.path for f in snapshot.files], ["a.py"])
        self.assertEqual(len(snapshot.skipped), 3)

    def test_total_text_budget(self):
        snapshot = collect_files([("a.py", b"first"), ("b.py", b"second")], max_total_bytes=8)
        self.assertEqual(len(snapshot.files), 1)
        self.assertEqual(snapshot.skipped[0]["reason"], "total text limit")

    def test_source_files_take_priority_over_large_reference_library(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("Project overview.", encoding="utf-8")
            (root / "requirements.txt").write_text("flask\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text('print("hello")', encoding="utf-8")
            (root / "knowledge").mkdir()
            for i in range(45):
                (root / "knowledge" / f"reference-{i}.md").write_text("Long background reading.", encoding="utf-8")
            snapshot = scan_project(root)
            self.assertEqual([f.path for f in snapshot.files[:3]],
                             ["README.md", "requirements.txt", "src/app.py"])
            self.assertEqual(len(snapshot.files), 40)

    def test_local_scan_leaves_project_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("A small project.", encoding="utf-8")
            (root / "app.py").write_text('print("hello")\n', encoding="utf-8")
            (root / ".env").write_text("PASSWORD=private", encoding="utf-8")
            (root / ".venv").mkdir()
            (root / ".venv" / "ignored.py").write_text("private", encoding="utf-8")
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            snapshot = scan_project(root)
            after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual([f.path for f in snapshot.files], ["README.md", "app.py"])
            self.assertNotIn("text", snapshot.manifest()["files"][0])


if __name__ == "__main__":
    unittest.main()
