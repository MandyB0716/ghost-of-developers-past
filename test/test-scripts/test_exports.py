import unittest
from unittest.mock import patch

from app import create_app
from export_formats import filename, markdown_export, pdf_export, references_for
from project_reader import collect_files
from revival_analysis import build_messages


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = collect_files([("README.md", b"Start here\nSOURCE_ONLY_SENTINEL\n"),
                                       ("app.py", b"print('hello')\n")])
        self.messages = build_messages(self.snapshot, "Return to this project.")
        self.text = "## Next steps\nRead the startup note [F1:L1]. Then inspect [F2]."

    def test_reference_list_resolves_exact_lines_without_inventing_file_ranges(self):
        labels = references_for(self.text + " Unknown [F1:L99].", self.messages)
        self.assertTrue(any("README.md, line 1" in label for label in labels))
        self.assertTrue(any("app.py (whole file; no line range cited)" in label for label in labels))
        self.assertTrue(any("F1:L99: source location unavailable" == label for label in labels))

    def test_markdown_preserves_response_and_excludes_source_text_and_goal(self):
        content = markdown_export(self.text, self.messages, "My project", 1).decode()
        self.assertIn(self.text, content)
        self.assertIn("Version 2", content)
        self.assertIn("File-and-line references", content)
        self.assertNotIn("SOURCE_ONLY_SENTINEL", content)
        self.assertNotIn("Return to this project.", content)

    def test_pdf_handles_literal_markup_and_does_not_fetch_remote_resources(self):
        hostile = self.text + '\n\n<img src="https://invalid.example/pixel"> & <b>literal</b>'
        with patch("urllib.request.urlopen", side_effect=AssertionError("No remote resources")):
            content = pdf_export(hostile, self.messages, "Test & review", 0)
        self.assertTrue(content.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", content[-30:])

    def test_filenames_are_bounded_and_cannot_inject_headers_or_paths(self):
        name = filename('../../A project\r\nX-Header: no', 0, "pdf")
        self.assertEqual(name, "a-project-x-header-no-restart-plan-v1.pdf")

    def test_routes_export_the_selected_version_and_reject_invalid_inputs(self):
        client = create_app(testing=True).test_client()
        client.post("/api/preview", json={"name":"My project", "files":[
            {"path":f.path,"text":f.text} for f in self.snapshot.files]})
        def result(content):
            return {"content":content,"seconds":0.1,"finish_reason":"stop","usage":{}}
        with patch("app.generate", side_effect=[result(self.text), result("## Revised\nRevised only [F1:L1].")]):
            client.post("/api/analyze", json={"goal":"Review."})
            client.post("/api/revise", json={"version":0,"feedback":"Clarify."})
        first = client.get("/api/export?version=0&format=md")
        second = client.get("/api/export?version=1&format=md")
        self.assertIn(b"Read the startup note", first.data)
        self.assertNotIn(b"Revised only", first.data)
        self.assertIn(b"Revised only", second.data)
        self.assertNotIn(b"SOURCE_ONLY_SENTINEL", first.data + second.data)
        pdf = client.get("/api/export?version=1&format=pdf")
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertIn("v2.pdf", pdf.headers["Content-Disposition"])
        self.assertTrue(pdf.data.startswith(b"%PDF-"))
        for query in ("version=abc", "version=-1", "version=20", "version=0&format=html"):
            self.assertEqual(client.get("/api/export?" + query).status_code, 400)


if __name__ == "__main__":
    unittest.main()
