"""Run the whole pipeline: ingest, transform, export, forecast.

    python run_pipeline.py [--full]

Equivalent to running each stage by hand:

    python -m pipeline.ingest
    dbt build (from the transform directory)
    python -m pipeline.export_marts
    python -m ml.forecast
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from pipeline import config


def find_dbt() -> str:
    venv_dbt = shutil.which("dbt", path=str(Path(sys.executable).parent))
    return venv_dbt or "dbt"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"\n=== {' '.join(cmd)} ===", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> None:
    ingest_cmd = [sys.executable, "-m", "pipeline.ingest"]
    if "--full" in sys.argv:
        ingest_cmd.append("--full")
    run(ingest_cmd, cwd=config.PROJECT_ROOT)

    dbt = find_dbt()
    run([dbt, "deps", "--profiles-dir", "."], cwd=config.TRANSFORM_DIR)
    run([dbt, "build", "--profiles-dir", "."], cwd=config.TRANSFORM_DIR)

    run([sys.executable, "-m", "pipeline.export_marts"], cwd=config.PROJECT_ROOT)

    run([sys.executable, "-m", "ml.forecast"], cwd=config.PROJECT_ROOT)
    print("\nPipeline finished.")


if __name__ == "__main__":
    main()
