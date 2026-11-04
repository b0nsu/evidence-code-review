#!/usr/bin/env python3
"""Validate review JSON v1.2 (or legacy v1.1) structure + limited internal consistency.

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
SCHEMA_VERSIONS = {"1.1", "1.2"}
MODES = {"review", "verify"}
SCOPE_KINDS = {"diff", "snapshot"}
VERDICTS = {"confirmed", "plausible", "rejected", "unverified"}


def valid_enum(value, allowed):
    return isinstance(value, str) and value in allowed


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
    version = review.get("schema_version")
    if not valid_enum(version, SCHEMA_VERSIONS):
        problems.append("schema_version must be '1.2' (or legacy '1.1')")
    legacy = version == "1.1"

    mode = "review"
    if legacy:
        for key in ("mode", "candidate_verdicts"):
            if key in review:
                problems.append(f"{key} requires schema_version '1.2'")
    else:
        mode = review.get("mode")
        if not valid_enum(mode, MODES):
            problems.append("mode invalid")

    scope = obj(review.get("scope"), "scope", problems)
    files = []
    if scope is not None:
        kind = "diff" if legacy else scope.get("kind")
        if legacy and "kind" in scope:
            problems.append("scope.kind requires schema_version '1.2'")
        if not legacy and not valid_enum(kind, SCOPE_KINDS):
            problems.append("scope.kind invalid")
        if kind == "snapshot":
            require_strings(scope, ("target",), "scope", problems)
            if scope.get("base") is not None:
                problems.append("scope.base must be omitted or null for a snapshot review")
        else:
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
        if not valid_enum(c.get("status"), CHECK_STATUSES):
            problems.append(f"checks[{i}].status invalid")

    qa = obj(review.get("quality_assessment"), "quality_assessment", problems)
    if qa is not None:
        for axis in sorted(AXES):
            if (a := obj(qa.get(axis), f"quality_assessment.{axis}", problems)) is None:
                continue
            if not valid_enum(a.get("status"), ASSESSMENTS):
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
        if not valid_enum(f.get("kind"), KINDS):
            problems.append(f"{prefix}.kind invalid")
        if not valid_enum(f.get("axis"), AXES):
            problems.append(f"{prefix}.axis invalid")
        if not valid_enum(f.get("severity"), SEVERITIES):
            problems.append(f"{prefix}.severity invalid")
        if not valid_enum(f.get("confidence"), CONFIDENCES):
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
            if not valid_enum(v.get("status"), VERIFICATION_STATUSES):
                problems.append(f"{prefix}.verification.status invalid")
            require_strings(v, ("detail",), f"{prefix}.verification", problems)

    for i, gap in enumerate(array(review.get("assurance_gaps"), "assurance_gaps", problems)):
        if (g := obj(gap, f"assurance_gaps[{i}]", problems)) is not None:
            require_strings(g, ("area", "risk", "discriminating_check", "evidence"), f"assurance_gaps[{i}]", problems)
    for i, unknown in enumerate(array(review.get("contract_unknowns"), "contract_unknowns", problems)):
        if (u := obj(unknown, f"contract_unknowns[{i}]", problems)) is not None:
            require_strings(u, ("question", "blocked_decision", "evidence"), f"contract_unknowns[{i}]", problems)

    has_unverified = False
    verdicts = review.get("candidate_verdicts", [])
    if not legacy and mode == "review" and verdicts not in ([], None):
        problems.append("candidate_verdicts must be omitted or empty when mode=review")
    if mode == "verify":
        verdicts = array(verdicts, "candidate_verdicts", problems)
        if not verdicts:
            problems.append("mode=verify requires a nonempty candidate_verdicts list")
        seen_candidates = set()
        for i, verdict in enumerate(verdicts):
            prefix = f"candidate_verdicts[{i}]"
            if (v := obj(verdict, prefix, problems)) is None:
                continue
            require_strings(v, ("candidate_id", "deciding_evidence"), prefix, problems)
            cid = v.get("candidate_id")
            if isinstance(cid, str):
                if cid in seen_candidates:
                    problems.append(f"{prefix}.candidate_id duplicated: {cid}")
                seen_candidates.add(cid)
            value = v.get("verdict")
            if not valid_enum(value, VERDICTS):
                problems.append(f"{prefix}.verdict invalid")
                continue
            if value == "confirmed":
                fid = v.get("finding_id")
                if not nonempty(fid):
                    problems.append(f"{prefix}.finding_id required for confirmed")
                elif fid not in seen_ids:
                    problems.append(f"{prefix}.finding_id {fid} does not match any finding")
            if value in ("plausible", "unverified") and not nonempty(v.get("limitation")):
                problems.append(f"{prefix}.limitation required for {value}")
            if value == "unverified":
                has_unverified = True

    conclusion = obj(review.get("conclusion"), "conclusion", problems)
    if conclusion is not None:
        status = conclusion.get("status")
        if not valid_enum(status, CONCLUSION_STATUSES):
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
        if has_unverified and status == "no_actionable_findings":
            problems.append("unverified candidates present; use incomplete (or issues_found with findings)")
    return problems


def main():
    if len(sys.argv) != 2:
        print("Usage: validate_review.py path/to/review.json", file=sys.stderr)
        return 2
    try:
        data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
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
