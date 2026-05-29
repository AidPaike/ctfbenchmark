from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from datasets.preprocessor.agent import LLMConfig
    from datasets.preprocessor.generator import generate_draft
else:
    from .agent import LLMConfig
    from .generator import generate_draft


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a raw CTF challenge directory into a Droplet/XBOW-like draft."
    )
    parser.add_argument("--raw-path", required=True, type=Path, help="Raw challenge directory.")
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Output draft dataset root, for example datasets/drafts/my-suite.",
    )
    parser.add_argument("--challenge-id", help="Public challenge id. Defaults to raw dir name.")
    parser.add_argument("--dataset-id", help="Dataset suite id. Defaults to output dir name.")
    parser.add_argument("--category", default="web", help="Droplet category for auto_discover.")
    parser.add_argument(
        "--task-type",
        default="web_ctf_online",
        help="Droplet task_type for auto_discover.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing challenge draft with the same id.",
    )
    parser.add_argument("--llm-provider", help="Optional LLM provider name; no key is read here.")
    parser.add_argument("--llm-model", help="Optional LLM model name.")
    parser.add_argument(
        "--llm-api-key-env",
        help="Environment-variable name that stores the API key; the value is never written.",
    )
    parser.add_argument("--llm-base-url", help="Optional LLM API base URL.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_config = LLMConfig.from_env()
    llm_config = LLMConfig(
        provider=args.llm_provider or env_config.provider,
        model=args.llm_model or env_config.model,
        api_key_env=args.llm_api_key_env or env_config.api_key_env,
        base_url=args.llm_base_url or env_config.base_url,
    )
    result = generate_draft(
        args.raw_path,
        args.output_dir,
        challenge_id=args.challenge_id,
        dataset_id=args.dataset_id,
        category=args.category,
        task_type=args.task_type,
        overwrite=args.overwrite,
        llm_config=llm_config,
    )
    print(
        json.dumps(
            {
                "dataset_root": str(result.dataset_root),
                "challenge_dir": str(result.challenge_dir),
                "challenge_id": result.challenge_id,
                "needs_review": result.needs_review,
                "compose_strategy": result.compose_strategy,
                "sensitive_paths": result.sensitive_paths,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
