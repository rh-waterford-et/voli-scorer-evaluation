"""Filesystem layout for the dashboard, anchored at the repository root."""

from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = DASHBOARD_DIR.parent
SCRIPTS_DIR = REPO_DIR / "scripts"
BENCHMARK_SCRIPT = SCRIPTS_DIR / "stream_metrics.py"
REPORTS_DIR = REPO_DIR / "reports"
DATA_DIR = DASHBOARD_DIR / "data"
RUNS_DIR = DATA_DIR / "runs"
FRONTEND_DIST = DASHBOARD_DIR / "frontend" / "dist"
