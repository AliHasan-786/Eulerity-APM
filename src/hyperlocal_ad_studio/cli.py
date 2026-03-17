from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .models import GenerationRequest
from .service import HyperLocalAdStudio


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HyperLocal Agentic Ad Studio prototype")
    parser.add_argument("--request-file", type=Path, help="Path to a JSON request payload.")
    parser.add_argument("--prompt", help="Corporate ad objective.")
    parser.add_argument("--zip", dest="zip_codes", action="append", default=[], help="Target zip code.")
    parser.add_argument("--guardrails", default="", help="Optional brand guardrails.")
    parser.add_argument(
        "--target-variants",
        type=int,
        default=50,
        help="Maximum number of variants to generate from the supplied zip codes.",
    )
    return parser.parse_args()


def _load_request(args: argparse.Namespace) -> GenerationRequest:
    if args.request_file:
        payload = json.loads(args.request_file.read_text(encoding="utf-8"))
        return GenerationRequest(
            corporate_prompt=str(payload["corporate_prompt"]).strip(),
            zip_codes=[str(zip_code) for zip_code in payload["zip_codes"]],
            brand_guardrails=str(payload.get("brand_guardrails", "")).strip(),
            target_variants=int(payload.get("target_variants", args.target_variants)),
        )
    if not args.prompt or not args.zip_codes:
        raise SystemExit("Provide either --request-file or both --prompt and at least one --zip.")
    return GenerationRequest(
        corporate_prompt=args.prompt.strip(),
        zip_codes=[str(zip_code) for zip_code in args.zip_codes],
        brand_guardrails=args.guardrails.strip(),
        target_variants=args.target_variants,
    )


def main() -> None:
    args = _parse_args()
    generation_request = _load_request(args)
    studio = HyperLocalAdStudio()
    result = asyncio.run(studio.generate_batch(generation_request))
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
