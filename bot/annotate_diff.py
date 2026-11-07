#!/usr/bin/env python3
"""Rewrite a unified diff so every line carries its real source line number.

A model that reads the raw diff with a file-viewing tool sees the viewer's own
line numbers (positions inside the diff file) and tends to cite those as
source lines. This output puts the old and new source line numbers in fixed
columns on each line, so the numbers in the content are the ones to cite.

  OLD   NEW  | content
   12    12  |  unchanged line
         13 +|  added line (cite 13)
   13      - |  removed line (exists only in the base revision)

Usage: annotate_diff.py < pr.diff > pr-annotated.diff
"""
from __future__ import annotations

import re
import sys

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
HEADER = (
    "# Annotated diff. Columns: OLD = line in the base revision, NEW = line in the target\n"
    "# revision (the checkout). Cite NEW numbers, or read the file in the checkout.\n"
    "# The line numbers your file viewer shows for THIS file are not source lines.\n"
)


def annotate(lines):
    yield HEADER
    old = new = None
    for raw in lines:
        line = raw.rstrip("\n")
        match = HUNK_RE.match(line)
        if match:
            old, new = int(match.group(1)), int(match.group(2))
            yield f"{line}\n"
            continue
        if old is None or line.startswith(("diff --git", "index ", "--- ", "+++ ", "new file", "deleted file",
                                           "similarity", "rename ", "old mode", "new mode", "Binary files")):
            if line.startswith("diff --git"):
                old = new = None
            yield f"{line}\n"
            continue
        if not line:
            yield "\n"
        elif line.startswith("\\"):
            yield f"{'':>6} {'':>6}   |{line}\n"
        elif line.startswith("+"):
            yield f"{'':>6} {new:>6} + |{line[1:]}\n"
            new += 1
        elif line.startswith("-"):
            yield f"{old:>6} {'':>6} - |{line[1:]}\n"
            old += 1
        else:
            yield f"{old:>6} {new:>6}   |{line[1:]}\n"
            old += 1
            new += 1


def main() -> int:
    sys.stdout.writelines(annotate(sys.stdin))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
