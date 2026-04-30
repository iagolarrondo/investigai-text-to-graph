from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_paths_from_config(config_path: Path) -> tuple[str, str]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return str(raw["output_seed_dir"]), str(raw["output_eval_dir"])


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run synthetic pipeline: generate -> build -> validate -> optional app launch."
    )
    parser.add_argument(
        "--config",
        default="src/synthetic/configs/large.yaml",
        help="Synthetic generator config path.",
    )
    parser.add_argument(
        "--launch-app",
        action="store_true",
        help="Launch Streamlit app after successful pipeline run.",
    )
    args = parser.parse_args()

    config_path = (PROJECT_ROOT / args.config).resolve()
    output_seed_dir, output_eval_dir = _read_paths_from_config(config_path)

    print(f"[1/4] Generating synthetic dataset from {config_path}")
    _run([sys.executable, "src/synthetic/generate_dataset.py", "--config", str(config_path)])

    print(f"[2/4] Building graph from {output_seed_dir}")
    _run([sys.executable, "src/graph_build/build_graph_files.py", "--seed-dir", output_seed_dir])

    print("[3/4] Validating pipeline outputs")
    _run(
        [
            sys.executable,
            "src/synthetic/validate_pipeline.py",
            "--seed-dir",
            output_seed_dir,
            "--eval-dir",
            output_eval_dir,
        ]
    )

    print("[4/4] Pipeline complete")
    if args.launch_app:
        print("Launching Streamlit app...")
        _run(["streamlit", "run", "src/app/app.py"])


if __name__ == "__main__":
    main()

