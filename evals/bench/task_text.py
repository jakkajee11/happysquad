#!/usr/bin/env python3
"""Print the task text for a bench row id from tasks.md (second column, backticks stripped)."""
import os
import sys

tasks = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks.md")
want = sys.argv[1]
for line in open(tasks):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) >= 2 and cells[0] == want:
        print(cells[1].replace("`", ""))
        sys.exit(0)
sys.exit(1)
