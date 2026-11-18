# -*- coding: utf-8 -*-
"""Bookbench starten: python start.py [Bücherordner]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bookbench.app import main  # noqa: E402

if __name__ == "__main__":
    main()
