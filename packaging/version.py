# -*- coding: utf-8 -*-
"""Gibt VERSION aus bookbench/version.py aus (für build_windows.bat und den Windows-Workflow, ohne bookbench
zu importieren). Bis 1.4 stand sie in bookbench/ui/help.py."""
import os
import re

WURZEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bookbench")
for name in (("version.py",), ("ui", "help.py")):
    try:
        with open(os.path.join(WURZEL, *name), encoding="utf-8") as f:
            m = re.search(r'^VERSION = "([^"]+)"', f.read(), re.M)
    except OSError:
        continue
    if m:
        print(m.group(1))
        break
