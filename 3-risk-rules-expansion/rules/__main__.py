"""python -m rules input.json --output result.json"""

import argparse
import json
from pathlib import Path
import sys

from .rule_engine import RuleTool, load_config


def main():
    parser = argparse.ArgumentParser(description="处理一份合同选定类别的结构化事实")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--policy", type=Path)
    args = parser.parse_args()
    try:
        payload = load_config(args.input)
        tool = RuleTool(config=load_config(args.policy) if args.policy else None)
        result = tool.review_batch(payload.get("document_id"), payload.get("items"))
        output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        else:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            print(output, end="")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
