import unittest

from project_reader import collect_files
from revival_analysis import RULES_PATH, SYSTEM_PROMPT, build_messages, build_revision_messages, check_references


class AnalysisEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = collect_files([("app.py", b"import json\nprint('ready')\n")])

    def test_prompt_includes_developer_goal_and_numbered_evidence(self):
        messages = build_messages(self.snapshot, "Finish CSV export.")
        self.assertIn("Finish CSV export.", messages[1]["content"])
        self.assertIn("1: import json", messages[1]["content"])
        self.assertIn("untrusted evidence", messages[0]["content"])
        self.assertEqual(messages[0]["content"], RULES_PATH.read_text(encoding="utf-8").strip())

    def test_empty_snapshot_and_goal_are_rejected_before_model_call(self):
        with self.assertRaises(ValueError):
            build_messages(collect_files([]), "Return to work.")
        with self.assertRaises(ValueError):
            build_messages(self.snapshot, "   ")

    def test_valid_references_are_resolved_to_actual_files(self):
        checked = check_references("Uses json [F1:L1-L2].", self.snapshot)
        self.assertEqual(checked["issues"], [])
        self.assertEqual(checked["valid"][0]["path"], "app.py")

    def test_fabricated_files_and_out_of_range_lines_are_flagged(self):
        text = "Invented [F9:L1]. Wrong range [F1:L2-L99]."
        checked = check_references(text, self.snapshot)
        self.assertEqual(len(checked["valid"]), 0)
        self.assertEqual(len(checked["issues"]), 3)
        self.assertEqual(text, "Invented [F9:L1]. Wrong range [F1:L2-L99].")

    def test_combined_citation_checks_each_target(self):
        checked = check_references("A finding [F1:L1, F9:L2].", self.snapshot)
        self.assertEqual(len(checked["valid"]), 1)
        self.assertIn("Unknown source: [F9:L2]", checked["issues"])

    def test_malformed_citation_is_flagged(self):
        checked = check_references("A finding [F1:L1-Ln].", self.snapshot)
        self.assertIn("Unrecognized source reference", checked["issues"][0])

    def test_redacted_lines_cannot_be_used_as_evidence(self):
        snapshot = collect_files([("app.py", b'API_KEY = "private-example"\nprint("ok")')])
        checked = check_references("A finding [F1:L1].", snapshot)
        self.assertIn("omitted credential line", checked["issues"][0])

    def test_revision_preserves_original_context_and_includes_exact_feedback(self):
        original = build_messages(self.snapshot, "Finish CSV export.")
        feedback = "Compare the README startup command to the supplied entry file."
        revised = build_revision_messages(original, "Original answer.", feedback)
        self.assertEqual(revised[:2], original)
        self.assertEqual(len(original), 2)
        self.assertEqual(revised[-2], {"role": "assistant", "content": "Original answer."})
        self.assertEqual(revised[-1], {"role": "user", "content": feedback})

    def test_empty_feedback_is_rejected(self):
        with self.assertRaises(ValueError):
            build_revision_messages([], "An answer.", " ")

    def test_revision_adopts_current_rules_without_changing_old_evidence_or_output(self):
        original = build_messages(self.snapshot, "Prepare the course deployment.")
        original[0]["content"] = "Legacy policy before follow-up rules."
        answer = "Which hosting service does your course require?"
        revised = build_revision_messages(original, answer, "The course requires Render.")
        self.assertEqual(revised[0], {"role":"system", "content":SYSTEM_PROMPT})
        self.assertEqual(revised[1], original[1])
        self.assertEqual(original[0]["content"], "Legacy policy before follow-up rules.")
        self.assertEqual(revised[-2], {"role":"assistant", "content":answer})

    def test_file_only_reference_is_valid_but_has_no_line_claim(self):
        checked = check_references("Project overview [F1].", self.snapshot)
        self.assertEqual(checked["issues"], [])
        reference = checked["valid"][0]
        self.assertEqual(reference["scope"], "file")
        self.assertIsNone(reference["first_line"])
        self.assertIsNone(reference["last_line"])

    def test_mixed_file_and_line_references_keep_their_distinct_scopes(self):
        checked = check_references("Overview [F1; F1:L2].", self.snapshot)
        self.assertEqual(checked["issues"], [])
        self.assertEqual([ref["scope"] for ref in checked["valid"]], ["file", "lines"])
        self.assertEqual(checked["valid"][1]["first_line"], 2)

    def test_file_range_cannot_expand_beyond_the_snapshot(self):
        checked = check_references("Invented files [F1-F999999999999999].", self.snapshot)
        self.assertEqual(checked["valid"], [])
        self.assertIn("Invalid source file range", checked["issues"][0])

    def test_reversed_file_range_is_rejected(self):
        checked = check_references("Wrong order [F2-F1].", self.snapshot)
        self.assertEqual(checked["valid"], [])
        self.assertIn("Invalid source file range", checked["issues"][0])


if __name__ == "__main__":
    unittest.main()
