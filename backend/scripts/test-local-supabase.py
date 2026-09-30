"""Run the local Supabase integration test without printing local credentials."""

import json
import os
from pathlib import Path
import subprocess
import sys


backend = Path(__file__).resolve().parents[1]
status = subprocess.run(
    ["supabase", "status", "--workdir", str(backend), "-o", "json"],
    capture_output=True, text=True, check=True,
)
settings = json.loads(status.stdout)
environment = os.environ.copy()
environment.update({
    "MEAL_PREP_TEST_SUPABASE_URL": settings["API_URL"],
    "MEAL_PREP_TEST_ANON_KEY": settings["ANON_KEY"],
    "MEAL_PREP_TEST_SERVICE_ROLE_KEY": settings["SERVICE_ROLE_KEY"],
})
result = subprocess.run(
    [sys.executable, "-m", "pytest", str(backend / "tests/test_supabase_integration.py"), "-q"],
    cwd=backend, env=environment, check=False,
)
raise SystemExit(result.returncode)
