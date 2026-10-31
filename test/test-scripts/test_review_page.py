import unittest
import re
import tempfile
from pathlib import Path

from project_reader import collect_files
from revival_analysis import build_messages
from review_page import refresh_saved_navigation, render_page, source_snapshot


class ReviewPageTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = collect_files([("app.py", b'print("hello")\nprint("bye")')])
        self.messages = build_messages(self.snapshot, "Understand startup.")

    def test_citation_targets_a_real_source_line(self):
        page = render_page("A finding [F1:L2].", self.messages, "Review")
        self.assertIn('href="#source-F1-L2"', page)
        self.assertIn('id="source-F1-L2"', page)
        self.assertIn('data-first="2" data-last="2"', page)

    def test_invalid_reference_is_not_linked(self):
        page = render_page("Wrong [F9:L99].", self.messages, "Review")
        self.assertNotIn('href="#source-F9-L99"', page)
        self.assertIn("Source location unavailable", page)

    def test_source_and_model_html_cannot_execute(self):
        snapshot = collect_files([("app.py", b'<script>alert("source")</script>')])
        messages = build_messages(snapshot, "Review.")
        page = render_page('<img src=x onerror="alert(1)"> [F1:L1]', messages, "<script>title</script>")
        self.assertNotIn('<img src=x', page)
        self.assertNotIn('<script>alert("source")', page)
        self.assertIn("&lt;img", page)
        self.assertIn("&lt;script&gt;", page)

    def test_combined_citations_link_to_each_location(self):
        page = render_page("A finding [F1:L1, F1:L2].", self.messages, "Review")
        self.assertIn('href="#source-F1-L1"', page)
        self.assertIn('href="#source-F1-L2"', page)

    def test_evidence_comes_from_saved_conversation(self):
        messages = self.messages + [{"role": "assistant", "content": "Old answer"},
                                    {"role": "user", "content": "Feedback, not replacement evidence."}]
        sources, goal = source_snapshot(messages)
        self.assertEqual(sources["F1"].text, self.snapshot.files[0].text)
        self.assertEqual(goal, "Understand startup.")

    def test_file_only_citation_opens_a_whole_file_without_invented_lines(self):
        page = render_page("Inspect this file [F1].", self.messages, "Review")
        link = re.search(r'<a class="citation file-citation"[^>]*>.*?</a>', page)[0]
        self.assertIn('href="#source-F1"', link)
        self.assertIn("app.py (file)", link)
        self.assertNotIn("data-first", link)
        self.assertNotIn("data-last", link)

    def test_file_range_expands_to_the_actual_supplied_files(self):
        snapshot = collect_files([("app.py", b"first"), ("src/helper.py", b"second")])
        messages = build_messages(snapshot, "Review.")
        page = render_page("Inspect both files [F1-F2].", messages, "Review")
        self.assertIn('href="#source-F1"', page)
        self.assertIn('href="#source-F2"', page)
        self.assertIn("src/helper.py (file)", page)

    def test_invalid_line_citation_does_not_fall_back_to_a_whole_file(self):
        page = render_page("Wrong line [F1:L999].", self.messages, "Review")
        self.assertNotIn('href="#source-F1"', page)
        self.assertIn("Source location unavailable", page)

    def test_unknown_file_range_is_not_partially_linked(self):
        page = render_page("Wrong files [F1-F9].", self.messages, "Review")
        self.assertNotIn('class="citation file-citation"', page)
        self.assertIn("Source location unavailable", page)

    def test_saved_navigation_copy_preserves_original_and_frozen_source(self):
        page = render_page("Keep this exact sentence [F1].", self.messages, "Review")
        old_page = re.sub(r'<a class="citation file-citation"[^>]*>.*?</a>',
                          '<span title="Source location unavailable">F1</span>', page)
        with tempfile.TemporaryDirectory() as temporary:
            source, destination = Path(temporary) / "original.html", Path(temporary) / "preview.html"
            source.write_text(old_page, encoding="utf-8")
            original_bytes = source.read_bytes()
            result = refresh_saved_navigation(source, destination)
            updated = destination.read_text(encoding="utf-8")
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(result["file_links_added"], 1)
            self.assertIn("Keep this exact sentence ", updated)
            self.assertIn('href="#source-F1"', updated)
            source_pattern = r'<section class="source-file".*?</section>'
            self.assertEqual(re.findall(source_pattern, old_page, re.S),
                             re.findall(source_pattern, updated, re.S))
            with self.assertRaises(FileExistsError):
                refresh_saved_navigation(source, destination)
            with self.assertRaisesRegex(ValueError, "new filename"):
                refresh_saved_navigation(source, source)


if __name__ == "__main__":
    unittest.main()
