# -*- coding: utf-8 -*-
"""Gibt VERSION aus bookbench/ui/help.py aus (für build_windows.bat, ohne bookbench zu importieren)."""
import os
import re

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bookbench", "ui", "help.py"),
          encoding="utf-8") as f:
    print(re.search(r'^VERSION = "([^"]+)"', f.read(), re.M).group(1))
