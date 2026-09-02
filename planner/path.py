"""planner.path — learning_path(): ordered sub-topics for a broad topic."""

from __future__ import annotations

import argparse
import json

from prompts import LEARNING_PATH_PROMPT, fill
import llm


def learning_path(topic: str) -> list[str]:
    prompt = fill(LEARNING_PATH_PROMPT, TOPIC=topic)
    data = llm.generate_json(prompt)
    steps = [str(s).strip() for s in (data.get("steps") or []) if str(s).strip()]
    if not steps:
        raise llm.LLMError("learning_path returned no steps.")
    return steps


def _main() -> None:
    parser = argparse.ArgumentParser(description="Build a learning path.")
    parser.add_argument("fixture", help="path to a JSON fixture")
    args = parser.parse_args()
    with open(args.fixture, encoding="utf-8") as f:
        data = json.load(f)
    result = learning_path(data["topic"])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()