"""Tests for bot/post_review.py.

The review fixture is the first JSON example in references/finding-contract.md,
so a contract change that breaks the bot shows up here too.

Run: python3 -m unittest discover -s tests
"""
from __future__ import annotations

import base64
import contextlib
import copy
import importlib.util
import io
import json
import pathlib
import re
import tempfile
import unittest
import urllib.error
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "references" / "finding-contract.md"

_spec = importlib.util.spec_from_file_location("post_review", ROOT / "bot" / "post_review.py")
post_review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(post_review)

_aspec = importlib.util.spec_from_file_location("annotate_diff", ROOT / "bot" / "annotate_diff.py")
annotate_diff = importlib.util.module_from_spec(_aspec)
_aspec.loader.exec_module(annotate_diff)

REVIEW = json.loads(re.findall(r"```json\n(.*?)```", CONTRACT.read_text(encoding="utf-8"), re.S)[0])
HEAD = "a" * 40

# Right side of src/orders.py: hunk 1 covers 40-44, hunk 2 covers 60-61.
ORDERS_PATCH = "\n".join([
    "@@ -40,4 +40,5 @@ def get_order(order_id):",
    "     session = db()",
    "-    q = session.query(Order).filter_by(id=order_id, owner=user)",
    "+    q = session.query(Order)",
    "+    q = q.filter_by(id=order_id)",
    "     return q.one()",
    " ",
    "@@ -58,2 +59,3 @@ def list_orders():",
    "-    pass",
    "+    x = 1",
    "+    return x",
    "\\ No newline at end of file",
])
FILES = [{"filename": "src/orders.py", "patch": ORDERS_PATCH}, {"filename": "logo.png"}]


def claude_output(review=None, text=None, **overrides):
    if text is None:
        text = "Review done.\n\n```json\n" + json.dumps(review if review is not None else REVIEW, indent=2) + "\n```"
    out = {"type": "result", "subtype": "success", "is_error": False, "result": text,
           "num_turns": 12, "total_cost_usd": 1.234, "modelUsage": {"claude-opus-5-5": {}}}
    out.update(overrides)
    return out


def finding(**changes):
    f = copy.deepcopy(REVIEW["findings"][0])
    for key, value in changes.items():
        if key == "location":
            f["location"].update(value)
        else:
            f[key] = value
    return f


class ExtractTests(unittest.TestCase):
    def test_last_parsable_block_wins(self):
        text = "Draft:\n```json\n{\"draft\": true}\n```\nFinal:\n```json\n" + json.dumps(REVIEW) + "\n```"
        self.assertEqual(post_review.extract_review(claude_output(text=text)), REVIEW)

    def test_bare_json_message_is_accepted(self):
        self.assertEqual(post_review.extract_review(claude_output(text=json.dumps(REVIEW))), REVIEW)

    def test_failed_run_is_rejected(self):
        with self.assertRaisesRegex(post_review.OutputError, "error_max_budget"):
            post_review.extract_review(claude_output(subtype="error_max_budget_usd", is_error=True))

    def test_message_without_json_is_rejected(self):
        with self.assertRaises(post_review.OutputError):
            post_review.extract_review(claude_output(text="I could not finish the review."))


class AnchorTests(unittest.TestCase):
    def test_parse_patch_keeps_right_side_lines_per_hunk(self):
        self.assertEqual(post_review.parse_patch(ORDERS_PATCH), [{40, 41, 42, 43, 44}, {59, 60}])

    def test_binary_file_has_no_hunks(self):
        self.assertEqual(post_review.parse_patch(None), [])

    def test_place(self):
        hunks = post_review.parse_patch(ORDERS_PATCH)
        cases = [
            ({"line_start": 42, "line_end": 43}, {"start_line": 42, "line": 43}),
            ({"line_start": 43, "line_end": 43}, {"line": 43}),
            ({"line_start": 30, "line_end": 41}, {"line": 41}),   # start outside the hunk
            ({"line_start": 44, "line_end": 59}, {"line": 59}),   # spans two hunks
            ({"line_start": 60, "line_end": 70}, {"line": 60}),   # only start commentable
            ({"line_start": 50, "line_end": 52}, None),           # between hunks
        ]
        for loc, expected in cases:
            with self.subTest(loc=loc):
                self.assertEqual(post_review.place(loc, hunks), expected)


class AnnotateDiffTests(unittest.TestCase):
    DIFF = "\n".join([
        "diff --git a/src/orders.py b/src/orders.py",
        "index 1111111..2222222 100644",
        "--- a/src/orders.py",
        "+++ b/src/orders.py",
        ORDERS_PATCH,
        "diff --git a/new.py b/new.py",
        "new file mode 100644",
        "--- /dev/null",
        "+++ b/new.py",
        "@@ -0,0 +1,2 @@",
        "+a",
        "+b",
    ]) + "\n"

    def rows(self):
        out = "".join(annotate_diff.annotate(io.StringIO(self.DIFF)))
        return [l for l in out.splitlines() if "|" in l and not l.startswith("#")]

    def test_new_side_numbers_follow_hunk_headers(self):
        new_numbers = []
        for row in self.rows():
            left, _, _ = row.partition("|")
            parts = left.split()
            if left.rstrip().endswith("-") or not parts or not parts[-1].isdigit() and parts[-1] != "+":
                continue
            nums = [p for p in parts if p.isdigit()]
            new_numbers.append(int(nums[-1]))
        # orders.py hunks: 40-44 and 59-60; new.py: 1-2.
        self.assertEqual(new_numbers, [40, 41, 42, 43, 44, 59, 60, 1, 2])

    def test_removed_lines_carry_only_the_old_number(self):
        removed = [r for r in self.rows() if r.split("|")[0].rstrip().endswith("-")]
        self.assertEqual([r.split()[0] for r in removed], ["41", "58"])

    def test_header_warns_about_viewer_line_numbers(self):
        out = "".join(annotate_diff.annotate(io.StringIO("")))
        self.assertIn("not source lines", out)


class PlanTests(unittest.TestCase):
    def plan(self, findings, comments=()):
        review = dict(REVIEW, findings=findings)
        return post_review.plan_review(review, post_review.hunks_from_files(FILES),
                                       post_review.posted_fingerprints(list(comments)))

    def test_high_confidence_p1_in_diff_goes_inline(self):
        plan = self.plan([finding()])
        self.assertEqual(len(plan["inline"]), 1)
        comment = plan["inline"][0][2]
        self.assertEqual((comment["path"], comment["start_line"], comment["line"]), ("src/orders.py", 42, 43))
        self.assertEqual((comment["side"], comment["start_side"]), ("RIGHT", "RIGHT"))
        self.assertIn("<!-- ecr:fp=", comment["body"])

    def test_body_reasons(self):
        plan = self.plan([
            finding(id="F2", title="Low impact", severity="P3"),
            finding(id="F3", title="Medium confidence", confidence="medium"),
            finding(id="F4", title="Unchanged caller", location={"line_start": 50, "line_end": 52}),
            finding(id="F5", title="Other file", location={"path": "src/other.py"}),
        ])
        self.assertEqual(plan["inline"], [])
        reasons = {f["id"]: reason for f, _, reason in plan["body"]}
        self.assertEqual(reasons, {
            "F2": "below the inline threshold",
            "F3": "below the inline threshold",
            "F4": "outside the diff",
            "F5": "outside the diff",
        })

    def test_bot_comment_with_same_fingerprint_is_not_repeated(self):
        fp = post_review.fingerprint(finding())
        # A later run moved the finding and reworded spacing/case of the title.
        moved = finding(title="  cross-tenant ORDER retrieval ", location={"line_start": 40, "line_end": 40})
        plan = self.plan([moved], [{"user": {"login": "github-actions[bot]"}, "body": f"x <!-- ecr:fp={fp} -->"}])
        self.assertEqual((len(plan["inline"]), len(plan["repeated"])), (0, 1))

    def test_marker_from_another_user_is_ignored(self):
        fp = post_review.fingerprint(finding())
        plan = self.plan([finding()], [{"user": {"login": "someone"}, "body": f"<!-- ecr:fp={fp} -->"}])
        self.assertEqual(len(plan["inline"]), 1)

    def test_line_past_end_of_file_is_never_inline(self):
        # A diff-file position (443) that happens to be cited for a 120-line file.
        plan = post_review.plan_review(
            dict(REVIEW, findings=[finding(location={"line_start": 42, "line_end": 443})]),
            post_review.hunks_from_files(FILES), set(), line_counts={"src/orders.py": 120})
        self.assertEqual(plan["inline"], [])
        self.assertEqual(plan["body"][0][2], "cited line is past the end of the file (120 lines)")

    def test_unknown_line_count_does_not_block_inline(self):
        plan = post_review.plan_review(REVIEW, post_review.hunks_from_files(FILES), set(), line_counts={"src/orders.py": None})
        self.assertEqual(len(plan["inline"]), 1)

    def test_findings_are_ordered_by_severity(self):
        plan = self.plan([finding(id="F2", title="b", severity="P2"), finding(id="F1", title="a", severity="P0")])
        self.assertEqual([f["id"] for f, _, _ in plan["inline"]], ["F1", "F2"])


class RenderTests(unittest.TestCase):
    def test_model_text_cannot_ping_or_forge_markers(self):
        f = finding(observation="cc @octocat and <!-- ecr:fp=000000000000 -->, mail a@b.c")
        body = post_review.render_finding(f, "abcdefabcdef")
        self.assertNotIn("@octocat", body)
        self.assertIn("a@b.c", body)
        self.assertEqual(post_review.FP_RE.findall(body), ["abcdefabcdef"])

    def test_summary_flags_target_mismatch_and_clean_result(self):
        review = dict(REVIEW, findings=[], conclusion={"status": "no_actionable_findings", "summary": "Nothing."})
        plan = post_review.plan_review(review, {}, set())
        body = post_review.render_summary(review, plan, head_sha=HEAD, run_url="https://x/run",
                                          run_note=None, rejected_anchors=False)
        self.assertTrue(body.startswith(post_review.SUMMARY_MARKER))
        self.assertIn("does not show the change is safe", body)
        self.assertIn("names target `working-tree`", body)
        self.assertIn("[workflow run](https://x/run)", body)

    def test_summary_lists_gaps_and_lenses(self):
        plan = post_review.plan_review(REVIEW, {}, set())
        body = post_review.render_summary(REVIEW, plan, head_sha="working-tree", run_url=None,
                                          run_note=None, rejected_anchors=False)
        self.assertNotIn("Warning:", body)
        self.assertIn("#### Assurance gaps", body)
        self.assertIn("| execution | risk |", body)
        self.assertIn("outside the diff", body)


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        (self.dir / "files.json").write_text(json.dumps(FILES))
        (self.dir / "comments.json").write_text("[]")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, output, extra=()):
        path = self.dir / "out.json"
        path.write_text(output if isinstance(output, str) else json.dumps(output))
        argv = ["--repo", "o/r", "--pr", "7", "--head-sha", HEAD, "--claude-output", str(path),
                "--files-json", str(self.dir / "files.json"), "--comments-json", str(self.dir / "comments.json"),
                *extra]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = post_review.main(argv)
        return code, stdout.getvalue()

    @staticmethod
    def requests(out):
        """Every request a --dry-run printed, in order."""
        decoder, pos, found = json.JSONDecoder(), 0, []
        while pos < len(out):
            if out[pos].isspace():
                pos += 1
                continue
            obj, pos = decoder.raw_decode(out, pos)
            found.append(obj)
        return found

    def issue_comments(self, comments):
        path = self.dir / "issue-comments.json"
        path.write_text(json.dumps(comments))
        return ["--issue-comments-json", str(path)]

    def test_dry_run_posts_one_review(self):
        code, out = self.run_main(claude_output(), ["--dry-run"])
        self.assertEqual(code, 0)
        [request] = self.requests(out)
        self.assertEqual((request["method"], request["path"]), ("POST", "/pulls/7/reviews"))
        self.assertEqual(request["payload"]["event"], "COMMENT")
        self.assertEqual(request["payload"]["commit_id"], HEAD)
        self.assertEqual(len(request["payload"]["comments"]), 1)
        self.assertIn("claude-opus-5-5 · 12 turns · $1.23", request["payload"]["body"])

    def test_invalid_review_posts_failure_comment(self):
        broken = copy.deepcopy(REVIEW)
        del broken["findings"][0]["trigger"]
        code, out = self.run_main(claude_output(broken), ["--dry-run"])
        self.assertEqual(code, 1)
        [request] = self.requests(out)
        self.assertEqual((request["method"], request["path"]), ("POST", "/issues/7/comments"))
        self.assertIn("findings[0].trigger must be a nonempty string", request["payload"]["body"])

    def test_unreadable_output_posts_failure_comment(self):
        code, out = self.run_main("not json", ["--dry-run"])
        self.assertEqual(code, 1)
        self.assertIn("cannot read Claude Code output", self.requests(out)[0]["payload"]["body"])

    def test_failure_edits_the_earlier_summary_comment(self):
        earlier = [{"id": 99, "user": {"login": "github-actions[bot]"}, "body": post_review.SUMMARY_MARKER + "\nold"}]
        code, out = self.run_main("not json", ["--dry-run", *self.issue_comments(earlier)])
        self.assertEqual(code, 1)
        [request] = self.requests(out)
        self.assertEqual((request["method"], request["path"]), ("PATCH", "/issues/comments/99"))

    def test_comment_mode_posts_inline_review_then_summary_comment(self):
        code, out = self.run_main(claude_output(), ["--dry-run", "--summary", "comment"])
        self.assertEqual(code, 0)
        review, summary = self.requests(out)
        self.assertEqual(review["path"], "/pulls/7/reviews")
        self.assertEqual(len(review["payload"]["comments"]), 1)
        self.assertTrue(review["payload"]["body"].startswith(post_review.REVIEW_MARKER))
        self.assertNotIn("Assurance gaps", review["payload"]["body"])
        self.assertEqual((summary["method"], summary["path"]), ("POST", "/issues/7/comments"))
        self.assertTrue(summary["payload"]["body"].startswith(post_review.SUMMARY_MARKER))
        self.assertIn("#### Assurance gaps", summary["payload"]["body"])

    def test_comment_mode_inlines_p3_and_medium_when_asked(self):
        review_doc = dict(REVIEW, findings=[finding(severity="P3", confidence="medium")])
        code, out = self.run_main(claude_output(review_doc), [
            "--dry-run", "--summary", "comment",
            "--inline-severities", "P0,P1,P2,P3", "--inline-confidences", "high,medium"])
        self.assertEqual(code, 0)
        review, summary = self.requests(out)
        self.assertEqual(len(review["payload"]["comments"]), 1)
        self.assertNotIn("#### Findings listed here", summary["payload"]["body"])

    def test_comment_mode_without_inline_findings_posts_only_the_summary(self):
        outside = dict(REVIEW, findings=[finding(location={"line_start": 50, "line_end": 52})])
        code, out = self.run_main(claude_output(outside), ["--dry-run", "--summary", "comment"])
        self.assertEqual(code, 0)
        [summary] = self.requests(out)
        self.assertEqual(summary["path"], "/issues/7/comments")
        self.assertIn("outside the diff", summary["payload"]["body"])

    def test_comment_mode_rerun_edits_summary_and_skips_posted_finding(self):
        fp = post_review.fingerprint(finding())
        (self.dir / "comments.json").write_text(json.dumps(
            [{"user": {"login": "github-actions[bot]"}, "body": f"x <!-- ecr:fp={fp} -->"}]))
        earlier = [
            {"id": 5, "user": {"login": "someone"}, "body": post_review.SUMMARY_MARKER + " forged"},
            {"id": 6, "user": {"login": "github-actions[bot]"}, "body": post_review.SUMMARY_MARKER + "\nold"},
        ]
        code, out = self.run_main(claude_output(), ["--dry-run", "--summary", "comment", *self.issue_comments(earlier)])
        self.assertEqual(code, 0)
        [summary] = self.requests(out)
        self.assertEqual((summary["method"], summary["path"]), ("PATCH", "/issues/comments/6"))
        self.assertIn("Already commented in an earlier run", summary["payload"]["body"])

    def test_rejected_anchor_falls_back_to_body(self):
        calls = []

        def fake_request(_self, method, url, data=None):
            if method == "GET":
                return {"encoding": "base64", "content": base64.b64encode(b"x\n" * 100).decode()}, ""
            calls.append(data)
            if len(calls) == 1:
                raise urllib.error.HTTPError(url, 422, "Unprocessable", {}, None)
            return {}, ""

        with mock.patch.object(post_review.GitHub, "request", fake_request), \
                mock.patch.dict("os.environ", {"GH_TOKEN": "t"}):
            code, _ = self.run_main(claude_output())
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(calls[0]["comments"]), 1)
        self.assertEqual(calls[1]["comments"], [])
        self.assertIn("GitHub rejected the inline anchor", calls[1]["body"])

    def test_comment_mode_rejected_anchor_moves_findings_to_summary(self):
        calls = []

        def fake_request(_self, method, url, data=None):
            calls.append((method, url, data))
            if method == "GET" and "/contents/" in url:
                return {"encoding": "base64", "content": base64.b64encode(b"x\n" * 100).decode()}, ""
            if method == "GET":
                return [], ""
            if url.endswith("/reviews"):
                raise urllib.error.HTTPError(url, 422, "Unprocessable", {}, None)
            return {}, ""

        with mock.patch.object(post_review.GitHub, "request", fake_request), \
                mock.patch.dict("os.environ", {"GH_TOKEN": "t"}):
            code, _ = self.run_main(claude_output(), ["--summary", "comment"])
        self.assertEqual(code, 0)
        writes = [(m, u.rsplit("/repos/o/r", 1)[-1]) for m, u, _ in calls if m != "GET"]
        self.assertEqual(writes, [("POST", "/pulls/7/reviews"), ("POST", "/issues/7/comments")])
        summary = calls[-1][2]["body"]
        self.assertIn("GitHub rejected the inline anchor", summary)
        self.assertIn("every finding is listed here", summary)


if __name__ == "__main__":
    unittest.main()
