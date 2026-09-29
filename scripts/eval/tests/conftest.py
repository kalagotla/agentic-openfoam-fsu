"""Put the eval modules on the import path.

Mirrors the idiom the rest of ``scripts/`` uses (``run_agent.py`` imports
``automation_gate`` the same way) rather than making ``scripts/eval`` an
installed package.
"""

from __future__ import annotations

import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = EVAL_DIR.parent
for d in (EVAL_DIR, SCRIPTS_DIR):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
