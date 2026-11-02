#!/usr/bin/env python3
"""Validate review JSON v1.1 structure + limited internal consistency.

This does NOT establish that a code defect exists, a test is valid, or a check ran.
Usage: python scripts/validate_review.py review.json
"""
from __future__ import annotations

import json
import pathlib
import sys

SEVERITIES = {"P0", "P1", "P2", "P3"}
CONFIDENCES = {"high", "medium"}
KINDS = {"code_defect", "test_defect", "contract_defect"}
AXES = {"direction", "execution", "verification"}
ASSESSMENTS = {"supported", "risk", "unknown"}
CHECK_STATUSES = {"pass", "fail", "not_run"}
VERIFICATION_STATUSES = {"executed", "static_trace"}
CONCLUSION_STATUSES = {"issues_found", "no_actionable_findings", "incomplete"}


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def obj(value, path, problems):
    if not isinstance(value, dict):
        problems.append(f"{path} must be an object")
        return None
    return value


def array(value, path, problems):
    if not isinstance(value, list):
        problems.append(f"{path} must be a list")
        return []
    return value


def require_strings(data, keys, path, problems):
    for key in keys:
        if not nonempty(data.get(key)):
            problems.append(f"{path}.{key} must be a nonempty string")


def validate(review):
    problems = []
    if not isinstance(review, dict):
        return ["root must be a JSON object"]
    if review.get("schema_version") != "1.1":
        problems.append("schema_version must be '1.1'")

    scope = obj(review.get("scope"), "scope", problems)
    files = []
    if scope is not None:
        require_strings(scope, ("base", "target"), "scope", problems)
        files = array(scope.get("files_reviewed"), "scope.files_reviewed", problems)
        for i, val in enumerate(files):
            if not nonempty(val):
                problems.append(f"scope.files_reviewed[{i}] must be a nonempty path")
        for i, val in enumerate(array(scope.get("limitations"), "scope.limitations", problems)):
            if not nonempty(val):
                problems.append(f"scope.limitations[{i}] must be a nonempty string")

    for i, check in enumerate(array(review.get("checks"), "checks", problems)):
        if (c := obj(check, f"checks[{i}]", problems)) is None:
            continue
        require_strings(c, ("command", "result"), f"checks[{i}]", problems)
        if c.get("status") not in CHECK_STATUSES:
            problems.append(f"checks[{i}].status invalid")

    qa = obj(review.get("quality_assessment"), "quality_assessment", problems)
    if qa is not None:
        for axis in sorted(AXES):
            if (a := obj(qa.get(axis), f"quality_assessment.{axis}", problems)) is None:
                continue
            if a.get("status") not in ASSESSMENTS:
                problems.append(f"quality_assessment.{axis}.status invalid")
            require_strings(a, ("support",), f"quality_assessment.{axis}", problems)

    findings = array(review.get("findings"), "findings", problems)
    seen_ids = set()
    for i, finding in enumerate(findings):
        prefix = f"findings[{i}]"
        if (f := obj(finding, prefix, problems)) is None:
            continue
        require_strings(f, ("id", "title", "observation", "trigger", "impact", "counterevidence", "recommendation"), prefix, problems)
        fid = f.get("id")
        if isinstance(fid, str):
            if fid in seen_ids:
                problems.append(f"{prefix}.id duplicated: {fid}")
            seen_ids.add(fid)
        if f.get("kind") not in KINDS:
            problems.append(f"{prefix}.kind invalid")
        if f.get("axis") not in AXES:
            problems.append(f"{prefix}.axis invalid")
        if f.get("severity") not in SEVERITIES:
            problems.append(f"{prefix}.severity invalid")
        if f.get("confidence") not in CONFIDENCES:
            problems.append(f"{prefix}.confidence invalid")
        if f.get("kind") == "test_defect" and not nonempty(f.get("test_counterexample")):
            problems.append(f"{prefix}.test_counterexample required for test_defect")
        if (l := obj(f.get("location"), f"{prefix}.location", problems)) is not None:
            require_strings(l, ("path",), f"{prefix}.location", problems)
            s, e = l.get("line_start"), l.get("line_end")
            if type(s) is not int or type(e) is not int or s < 1 or e < s:
                problems.append(f"{prefix}.location lines must be positive and ordered")
        if (contract := obj(f.get("contract"), f"{prefix}.contract", problems)) is not None:
            require_strings(contract, ("source", "expectation"), f"{prefix}.contract", problems)
        if (v := obj(f.get("verification"), f"{prefix}.verification", problems)) is not None:
            if v.get("status") not in VERIFICATION_STATUSES:
                problems.append(f"{prefix}.verification.status invalid")
            require_strings(v, ("detail",), f"{prefix}.verification", problems)

    for i, gap in enumerate(array(review.get("assurance_gaps"), "assurance_gaps", problems)):
        if (g := obj(gap, f"assurance_gaps[{i}]", problems)) is not None:
            require_strings(g, ("area", "risk", "discriminating_check", "evidence"), f"assurance_gaps[{i}]", problems)
    for i, unknown in enumerate(array(review.get("contract_unknowns"), "contract_unknowns", problems)):
        if (u := obj(unknown, f"contract_unknowns[{i}]", problems)) is not None:
            require_strings(u, ("question", "blocked_decision", "evidence"), f"contract_unknowns[{i}]", problems)

    conclusion = obj(review.get("conclusion"), "conclusion", problems)
    if conclusion is not None:
        status = conclusion.get("status")
        if status not in CONCLUSION_STATUSES:
            problems.append("conclusion.status invalid")
        require_strings(conclusion, ("summary",), "conclusion", problems)
        if status == "issues_found" and not findings:
            problems.append("conclusion claims issues_found but findings is empty")
        if status == "no_actionable_findings" and findings:
            problems.append("conclusion claims no_actionable_findings but findings present")
        if status == "incomplete" and findings:
            problems.append("conclusion claims incomplete while confirmed findings present; use issues_found and report limits")
        if not files and status != "incomplete":
            problems.append("empty reviewed scope must use conclusion.status=incomplete")
    return problems


def main():
    if len(sys.argv) != 2:
        print("Usage: validate_review.py path/to/review.json", file=sys.stderr)
        return 2
    try:
        data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot load JSON: {exc}", file=sys.stderr)
        return 2
    issues = validate(data)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    print("STRUCTURE/CONSISTENCY VALID — factual correctness NOT assessed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
