#!/usr/bin/env python3
"""Post an evidence-code-review result to a pull request as one GitHub review.

Steps: take the JSON review out of Claude Code's `--output-format json` output,
check it with scripts/validate_review.py, anchor findings as inline comments
where GitHub accepts them, put everything else in the review body, and post.

This script holds the write token and never runs a model. The review job that
runs the model has no write token. Failures to extract or validate are posted
as a short PR comment and exit with status 1.

With --summary comment, the review carries only the inline comments and the
summary goes into one PR comment that later runs edit in place.

Usage:
  post_review.py --repo OWNER/NAME --pr N --head-sha SHA \
      --claude-output claude-output.json [--run-url URL] \
      [--summary review|comment] [--inline-severities P0,P1,P2,P3] \
      [--inline-confidences high,medium] \
      [--files-json files.json --comments-json comments.json \
       --issue-comments-json issue-comments.json] [--dry-run]

Environment: GH_TOKEN or GITHUB_TOKEN (not needed with --dry-run and both
--files-json and --comments-json), GITHUB_API_URL (optional).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate_review.py"

SUMMARY_MARKER = "<!-- evidence-code-review -->"
REVIEW_MARKER = "<!-- evidence-code-review:inline -->"
SUMMARY_MODES = ("review", "comment")
FP_RE = re.compile(r"<!-- ecr:fp=([0-9a-f]{12}) -->")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
BOT_LOGIN = "github-actions[bot]"
BODY_LIMIT = 60000  # GitHub rejects bodies over 65536 characters.
SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
DEFAULT_INLINE_SEVERITIES = ("P0", "P1", "P2")
DEFAULT_INLINE_CONFIDENCES = ("high",)


class OutputError(Exception):
    """Claude Code's output holds no usable review."""


def load_validate():
    spec = importlib.util.spec_from_file_location("validate_review", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate


# ---------------------------------------------------------------- extraction

def extract_review(claude_output) -> dict:
    """Return the review document from Claude Code's JSON output.

    The prompt asks for one ```json block at the end of the final message.
    The last block that parses to an object wins.
    """
    if not isinstance(claude_output, dict):
        raise OutputError("Claude Code output is not a JSON object")
    if claude_output.get("is_error") or claude_output.get("subtype") != "success":
        raise OutputError(
            "Claude Code run did not succeed "
            f"(subtype={claude_output.get('subtype')!r}, "
            f"terminal_reason={claude_output.get('terminal_reason')!r})"
        )
    text = claude_output.get("result")
    if not isinstance(text, str) or not text.strip():
        raise OutputError("Claude Code returned an empty final message")
    blocks = re.findall(r"```json[ \t]*\n(.*?)\n[ \t]*```", text, re.S)
    for raw in reversed(blocks or [text]):
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict):
            return doc
    raise OutputError("the final message holds no parsable ```json review block")


# ------------------------------------------------------------------- anchors

def parse_patch(patch) -> list[set[int]]:
    """Right-side line numbers GitHub accepts for comments, one set per hunk."""
    hunks: list[set[int]] = []
    current = None
    line = 0
    for raw in (patch or "").split("\n"):
        match = HUNK_RE.match(raw)
        if match:
            current = set()
            hunks.append(current)
            line = int(match.group(1))
            continue
        if current is None or not raw or raw[0] not in "+ ":
            continue  # removed lines, "\ No newline", split artifacts
        current.add(line)
        line += 1
    return hunks


def place(location: dict, hunks: list[set[int]]):
    """Choose a review-comment anchor inside one hunk, or None."""
    start = location.get("line_start")
    end = location.get("line_end", start)
    if type(start) is not int:
        return None
    if type(end) is not int or end < start:
        end = start
    for hunk in hunks:
        if end in hunk:
            if start != end and start in hunk:
                return {"start_line": start, "line": end}
            return {"line": end}
    for hunk in hunks:
        if start in hunk:
            return {"line": start}
    return None


def fingerprint(finding: dict) -> str:
    """Stable id across runs: path, kind and normalized title, no line."""
    loc = finding.get("location") or {}
    title = " ".join(str(finding.get("title", "")).lower().split())
    key = "|".join((str(loc.get("path", "")), str(finding.get("kind", "")), title))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


# ----------------------------------------------------------------- rendering

def clean(value) -> str:
    """Neutralize text from the model before it reaches GitHub markdown.

    Breaks @mentions so a review never pings people, and HTML comments so
    model text cannot forge this bot's markers.
    """
    text = str(value)
    text = text.replace("<!--", "&lt;!--")
    return re.sub(r"(?<![\w`])@(?=[A-Za-z0-9])", "@\u200b", text)


def sentence(value) -> str:
    text = clean(value).strip()
    return text if not text or text[-1] in ".!?:;)" else text + "."


def cell(value) -> str:
    return clean(value).replace("|", "\\|").replace("\n", " ")


def lines_label(loc: dict) -> str:
    start, end = loc.get("line_start"), loc.get("line_end")
    if end is None or end == start:
        return f"{loc.get('path')}:{start}"
    return f"{loc.get('path')}:{start}-{end}"


def render_finding(finding: dict, fp: str) -> str:
    contract = finding.get("contract") or {}
    verification = finding.get("verification") or {}
    parts = [
        f"**[{finding.get('severity')}] {clean(finding.get('title'))}**",
        f"`{finding.get('kind')}` · {finding.get('axis')} · confidence {finding.get('confidence')}",
        clean(finding.get("observation")),
        "\n".join(
            [
                f"- Trigger: {clean(finding.get('trigger'))}",
                f"- Impact: {clean(finding.get('impact'))}",
                f"- Contract: {clean(contract.get('source'))}: {clean(contract.get('expectation'))}",
                f"- Counterevidence checked: {clean(finding.get('counterevidence'))}",
                f"- Verification: `{verification.get('status')}`, {clean(verification.get('detail'))}",
            ]
            + (
                [f"- Test counterexample: {clean(finding['test_counterexample'])}"]
                if finding.get("test_counterexample")
                else []
            )
        ),
        f"Suggested fix: {clean(finding.get('recommendation'))}",
        f"<!-- ecr:fp={fp} -->",
    ]
    return "\n\n".join(parts)


def short(sha) -> str:
    return str(sha)[:12] if sha else "?"


def render_summary(review: dict, plan: dict, *, head_sha: str, run_url: str | None,
                   run_note: str | None, rejected_anchors: bool) -> str:
    conclusion = review.get("conclusion") or {}
    status = conclusion.get("status", "?")
    titles = {
        "issues_found": "issues found",
        "no_actionable_findings": "no actionable findings",
        "incomplete": "incomplete",
    }
    out = [SUMMARY_MARKER, f"### Evidence code review: {titles.get(status, status)}"]
    out.append(clean(conclusion.get("summary", "")))
    if status == "no_actionable_findings":
        out.append("No evidence-based defect was found in the inspected scope. That does not show the change is safe.")

    scope = review.get("scope") or {}
    warnings = []
    if scope.get("kind") != "diff":
        warnings.append(f"the review is a `{cell(scope.get('kind'))}` review, not a diff review")
    if scope.get("target") != head_sha:
        warnings.append(f"the review names target `{cell(scope.get('target'))}`, the PR head is `{short(head_sha)}`")
    if rejected_anchors:
        warnings.append("GitHub rejected the inline anchors, so every finding is listed here")
    if warnings:
        out.append("Warning: " + "; ".join(warnings) + ".")

    total = len(review.get("findings") or [])
    if total:
        out.append(
            f"Findings: {total} (inline: {len(plan['inline'])}, listed here: {len(plan['body'])}, "
            f"already commented in an earlier run: {len(plan['repeated'])})"
        )

    if plan["body"]:
        out.append("#### Findings listed here")
        for finding, fp, reason in plan["body"]:
            out.append(
                f"<details><summary>[{finding.get('severity')}] {cell(finding.get('title'))} · "
                f"<code>{cell(lines_label(finding.get('location') or {}))}</code> · {reason}</summary>\n\n"
                f"{render_finding(finding, fp)}\n\n</details>"
            )
    if plan["repeated"]:
        out.append("#### Already commented in an earlier run")
        out.append("\n".join(
            f"- [{f.get('severity')}] {cell(f.get('title'))} (`{cell(lines_label(f.get('location') or {}))}`)"
            for f in plan["repeated"]
        ))

    verdicts = review.get("candidate_verdicts") or []
    if verdicts:
        out.append("#### Candidate verdicts")
        rows = ["| Candidate | Verdict | Deciding evidence | Limitation |", "|---|---|---|---|"]
        rows += [
            f"| {cell(v.get('candidate_id'))} | {cell(v.get('verdict'))} | "
            f"{cell(v.get('deciding_evidence'))} | {cell(v.get('limitation', ''))} |"
            for v in verdicts
        ]
        out.append("\n".join(rows))

    gaps = review.get("assurance_gaps") or []
    if gaps:
        out.append("#### Assurance gaps")
        out.append("\n".join(
            f"- `{cell(g.get('area'))}`: {sentence(g.get('risk'))} Check that would tell: {sentence(g.get('discriminating_check'))}"
            for g in gaps
        ))
    unknowns = review.get("contract_unknowns") or []
    if unknowns:
        out.append("#### Contract unknowns")
        out.append("\n".join(
            f"- {sentence(u.get('question'))} Blocks: {sentence(u.get('blocked_decision'))} Evidence: {sentence(u.get('evidence'))}"
            for u in unknowns
        ))

    qa = review.get("quality_assessment") or {}
    if qa:
        rows = ["| Lens | Status | Evidence or limitation |", "|---|---|---|"]
        for axis in ("direction", "execution", "verification"):
            entry = qa.get(axis) or {}
            rows.append(f"| {axis} | {cell(entry.get('status'))} | {cell(entry.get('support'))} |")
        out.append("#### Three-lens assessment\n\n" + "\n".join(rows))

    files = scope.get("files_reviewed") or []
    scope_lines = [
        f"- Diff: `{cell(short(scope.get('base')))}...{cell(short(scope.get('target')))}`, {len(files)} files reviewed",
    ]
    scope_lines += [
        f"- Check `{cell(c.get('command'))}`: {cell(c.get('status'))}, {clean(c.get('result'))}"
        for c in review.get("checks") or []
    ]
    scope_lines += [f"- Limitation: {clean(item)}" for item in scope.get("limitations") or []]
    out.append("<details><summary>Scope and checks</summary>\n\n" + "\n".join(scope_lines) + "\n\n</details>")

    footer = []
    if run_note:
        footer.append(run_note)
    if run_url:
        footer.append(f"[workflow run]({run_url})")
    if footer:
        out.append("<sub>" + " · ".join(footer) + "</sub>")

    body = "\n\n".join(part for part in out if part)
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT] + "\n\n_(truncated; see the workflow run artifact for the full review)_"
    return body


def render_failure(reason: str, run_url: str | None) -> str:
    reason = reason if len(reason) <= 3000 else reason[:3000] + "\n..."
    parts = [
        SUMMARY_MARKER,
        "### Evidence code review produced no usable review",
        "```text\n" + reason.replace("```", "'''") + "\n```",
    ]
    if run_url:
        parts.append(f"The raw output is in the [workflow run]({run_url}) artifact.")
    return "\n\n".join(parts)


# ------------------------------------------------------------------ planning

def plan_review(review: dict, hunks_by_path: dict, posted_fps: set,
                inline_severities=DEFAULT_INLINE_SEVERITIES,
                inline_confidences=DEFAULT_INLINE_CONFIDENCES,
                line_counts: dict | None = None) -> dict:
    """Split findings into inline comments, summary entries and repeats.

    line_counts maps a path to its line count at the reviewed revision. A
    finding whose cited lines run past the end of its file has a wrong line
    number (for example a position inside the diff file), so it is never
    anchored inline, even if the bad number happens to fall in a hunk.
    """
    line_counts = line_counts or {}
    inline, body, repeated = [], [], []
    findings = sorted(
        review.get("findings") or [],
        key=lambda f: (SEVERITY_ORDER.get(f.get("severity"), 9), f.get("confidence") != "high"),
    )
    for finding in findings:
        fp = fingerprint(finding)
        loc = finding.get("location") or {}
        if fp in posted_fps:
            repeated.append(finding)
            continue
        if finding.get("severity") not in inline_severities or finding.get("confidence") not in inline_confidences:
            body.append((finding, fp, "below the inline threshold"))
            continue
        count = line_counts.get(loc.get("path"))
        end = max(loc.get("line_start") or 0, loc.get("line_end") or 0)
        if isinstance(count, int) and end > count:
            body.append((finding, fp, f"cited line is past the end of the file ({count} lines)"))
            continue
        anchor = place(loc, hunks_by_path.get(loc.get("path"), []))
        if anchor is None:
            body.append((finding, fp, "outside the diff"))
            continue
        comment = {"path": loc.get("path"), "side": "RIGHT", "body": render_finding(finding, fp), **anchor}
        if "start_line" in anchor:
            comment["start_side"] = "RIGHT"
        inline.append((finding, fp, comment))
    return {"inline": inline, "body": body, "repeated": repeated}


def without_inline(plan: dict, reason: str) -> dict:
    moved = [(f, fp, reason) for f, fp, _ in plan["inline"]]
    return {"inline": [], "body": moved + plan["body"], "repeated": plan["repeated"]}


def build_payload(review: dict, plan: dict, *, head_sha: str, run_url=None,
                  run_note=None, rejected_anchors=False) -> dict:
    """One review whose body is the full summary (summary mode "review")."""
    return {
        "commit_id": head_sha,
        "event": "COMMENT",
        "body": render_summary(review, plan, head_sha=head_sha, run_url=run_url,
                               run_note=run_note, rejected_anchors=rejected_anchors),
        "comments": [comment for _, _, comment in plan["inline"]],
    }


def build_inline_payload(plan: dict, *, head_sha: str) -> dict:
    """A review that carries only the inline comments (summary mode "comment")."""
    count = len(plan["inline"])
    return {
        "commit_id": head_sha,
        "event": "COMMENT",
        "body": f"{REVIEW_MARKER}\nEvidence code review: {count} finding{'s' if count != 1 else ''} "
                "commented inline. The summary and open questions are in a separate comment.",
        "comments": [comment for _, _, comment in plan["inline"]],
    }


def find_summary_comment(issue_comments: list):
    """The bot's earlier summary or failure comment, so a rerun edits it in place."""
    for comment in issue_comments:
        if (comment.get("user") or {}).get("login") == BOT_LOGIN and \
                (comment.get("body") or "").startswith(SUMMARY_MARKER):
            return comment
    return None


def posted_fingerprints(comments: list) -> set:
    fps = set()
    for comment in comments:
        if (comment.get("user") or {}).get("login") != BOT_LOGIN:
            continue
        fps.update(FP_RE.findall(comment.get("body") or ""))
    return fps


def hunks_from_files(files: list) -> dict:
    return {f.get("filename"): parse_patch(f.get("patch")) for f in files}


def count_lines(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def cited_paths(review: dict) -> list:
    return sorted({(f.get("location") or {}).get("path") for f in review.get("findings") or []} - {None})


def run_note_from(output: dict) -> str | None:
    if not isinstance(output, dict):
        return None
    bits = []
    models = list((output.get("modelUsage") or {}).keys())
    if models:
        bits.append(", ".join(models))
    if output.get("num_turns") is not None:
        bits.append(f"{output['num_turns']} turns")
    if isinstance(output.get("total_cost_usd"), (int, float)):
        bits.append(f"${output['total_cost_usd']:.2f}")
    return " · ".join(bits) or None


# -------------------------------------------------------------------- GitHub

class GitHub:
    def __init__(self, repo: str, token: str, api: str | None = None):
        self.base = f"{(api or 'https://api.github.com').rstrip('/')}/repos/{repo}"
        self.token = token

    def request(self, method: str, url: str, data=None):
        if not url.startswith("http"):
            url = self.base + url
        req = urllib.request.Request(
            url,
            method=method,
            data=None if data is None else json.dumps(data).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "evidence-code-review-bot",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return (json.loads(raw) if raw else None), resp.headers.get("Link", "")

    def line_count(self, path: str, ref: str):
        """Line count of a file at ref, or None when it cannot be read."""
        try:
            data, _ = self.request("GET", f"/contents/{urllib.parse.quote(path)}?ref={ref}")
        except urllib.error.HTTPError:
            return None
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        try:
            return count_lines(base64.b64decode(data.get("content", "")).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def paginate(self, path: str) -> list:
        url = self.base + path + ("&" if "?" in path else "?") + "per_page=100"
        items = []
        while url:
            data, link = self.request("GET", url)
            items.extend(data or [])
            match = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = match.group(1) if match else None
        return items


# ---------------------------------------------------------------------- main

def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--claude-output", required=True, type=pathlib.Path)
    parser.add_argument("--run-url")
    parser.add_argument("--files-json", type=pathlib.Path, help="PR files list instead of the API")
    parser.add_argument("--comments-json", type=pathlib.Path, help="PR review comments instead of the API")
    parser.add_argument("--line-counts-json", type=pathlib.Path,
                        help="{path: line count} at the head revision instead of the API (offline runs default to none)")
    parser.add_argument("--issue-comments-json", type=pathlib.Path,
                        help="PR conversation comments instead of the API (offline runs default to none)")
    parser.add_argument("--inline-severities", default=",".join(DEFAULT_INLINE_SEVERITIES))
    parser.add_argument("--inline-confidences", default=",".join(DEFAULT_INLINE_CONFIDENCES))
    parser.add_argument("--summary", choices=SUMMARY_MODES, default="review",
                        help="review: summary is the review body. comment: inline comments in a review, "
                             "summary in one PR comment that later runs edit in place")
    parser.add_argument("--dry-run", action="store_true", help="print the request instead of posting")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    offline = args.files_json is not None and args.comments_json is not None
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token and not (args.dry_run and offline):
        print("GH_TOKEN or GITHUB_TOKEN is required", file=sys.stderr)
        return 2
    gh = GitHub(args.repo, token or "", os.environ.get("GITHUB_API_URL"))

    def emit(path, payload, method="POST"):
        if args.dry_run:
            print(json.dumps({"method": method, "path": path, "payload": payload}, indent=2, ensure_ascii=False))
        else:
            gh.request(method, path, payload)

    def issue_comments():
        if args.issue_comments_json is not None:
            return json.loads(args.issue_comments_json.read_text(encoding="utf-8"))
        return [] if offline else gh.paginate(f"/issues/{args.pr}/comments")

    def upsert_summary(body):
        existing = find_summary_comment(issue_comments())
        if existing:
            emit(f"/issues/comments/{existing['id']}", {"body": body}, method="PATCH")
        else:
            emit(f"/issues/{args.pr}/comments", {"body": body})

    output = None
    try:
        try:
            output = json.loads(args.claude_output.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OutputError(f"cannot read Claude Code output: {exc}") from exc
        review = extract_review(output)
        problems = load_validate()(review)
        if problems:
            raise OutputError("review JSON failed validation:\n" + "\n".join(f"- {p}" for p in problems))
    except OutputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        upsert_summary(render_failure(str(exc), args.run_url))
        return 1

    if offline:
        files = json.loads(args.files_json.read_text(encoding="utf-8"))
        comments = json.loads(args.comments_json.read_text(encoding="utf-8"))
    else:
        files = gh.paginate(f"/pulls/{args.pr}/files")
        comments = gh.paginate(f"/pulls/{args.pr}/comments")

    if args.line_counts_json is not None:
        line_counts = json.loads(args.line_counts_json.read_text(encoding="utf-8"))
    elif offline:
        line_counts = {}
    else:
        line_counts = {p: gh.line_count(p, args.head_sha) for p in cited_paths(review)}

    plan = plan_review(
        review,
        hunks_from_files(files),
        posted_fingerprints(comments),
        inline_severities=tuple(s for s in args.inline_severities.split(",") if s),
        inline_confidences=tuple(c for c in args.inline_confidences.split(",") if c),
        line_counts=line_counts,
    )
    note = run_note_from(output)
    path = f"/pulls/{args.pr}/reviews"
    rejected = False

    if args.summary == "review":
        try:
            emit(path, build_payload(review, plan, head_sha=args.head_sha, run_url=args.run_url, run_note=note))
        except urllib.error.HTTPError as exc:
            if exc.code != 422 or not plan["inline"]:
                raise
            print(f"GitHub rejected the review ({exc.code}); retrying without inline comments", file=sys.stderr)
            plan = without_inline(plan, "GitHub rejected the inline anchor")
            emit(path, build_payload(review, plan, head_sha=args.head_sha, run_url=args.run_url,
                                     run_note=note, rejected_anchors=True))
    else:
        if plan["inline"]:
            try:
                emit(path, build_inline_payload(plan, head_sha=args.head_sha))
            except urllib.error.HTTPError as exc:
                if exc.code != 422:
                    raise
                print(f"GitHub rejected the inline review ({exc.code}); listing findings in the summary",
                      file=sys.stderr)
                plan = without_inline(plan, "GitHub rejected the inline anchor")
                rejected = True
        upsert_summary(render_summary(review, plan, head_sha=args.head_sha, run_url=args.run_url,
                                      run_note=note, rejected_anchors=rejected))

    print(f"{'Planned' if args.dry_run else 'Posted'} ({args.summary} summary): {len(plan['inline'])} inline, "
          f"{len(plan['body'])} listed in the summary, {len(plan['repeated'])} already commented", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
