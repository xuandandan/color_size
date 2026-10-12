from __future__ import annotations

import argparse
import json

from .ml import MLRuntime


def main() -> None:
    parser = argparse.ArgumentParser(description="Train paint recommendation models.")
    parser.add_argument("--min-samples", type=int, default=20, help="Minimum sample count required for training")
    parser.add_argument("--save-dir", type=str, default="models", help="Directory to save model artifacts")
    args = parser.parse_args()

    runtime = MLRuntime(model_dir=args.save_dir)
    metadata = runtime.train(min_samples=args.min_samples)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
