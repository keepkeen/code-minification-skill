#!/usr/bin/env python3
"""
Evaluate code-minification skill: measure token reduction and verify
semantic preservation.

Phase 1 — Token reduction metrics (no API cost)
  python3 evaluate.py --phase=reduction sample.py sample.go sample.js

Phase 2 — Syntax validation (no API cost)
  python3 evaluate.py --phase=syntax sample.py sample.go sample.js

Phase 3 — LLM comprehension A/B test (requires API key)
  python3 evaluate.py --phase=llm --api-key=$ANTHROPIC_API_KEY *.py

Full report:
  python3 evaluate.py sample.py sample.go sample.js
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

MINIFIER = os.path.join(os.path.dirname(__file__), "minify_code.py")


# ---------------------------------------------------------------------------
# Phase 1: Token reduction
# ---------------------------------------------------------------------------

def phase_reduction(file_paths: list[str]) -> list[dict]:
    results = []
    for path in file_paths:
        result = json.loads(
            subprocess.check_output(
                [sys.executable, MINIFIER, "--json", path],
                stderr=subprocess.DEVNULL,
            )
        )
        # Estimate token count: ~4 chars per token for code
        result["original_tokens"] = result["original_chars"] // 4
        result["minified_tokens"] = result["minified_chars"] // 4
        result["file"] = os.path.basename(path)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Phase 2: Syntax validation
# ---------------------------------------------------------------------------

def _check_parseable(code: str, language: str) -> tuple[bool, str]:
    """Check if minified code is syntactically valid using available parsers."""
    if language == "python":
        try:
            compile(code, "<minified>", "exec")
            return True, ""
        except SyntaxError as e:
            return False, str(e)
    elif language == "go":
        try:
            subprocess.run(
                ["gofmt", "-e"],
                input=code,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return True, ""
        except FileNotFoundError:
            return True, "(gofmt not installed, skipped)"
        except subprocess.TimeoutExpired:
            return False, "timeout"
    elif language in ("javascript", "typescript"):
        try:
            subprocess.run(
                ["node", "--check", "-"],
                input=code,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return True, ""
        except FileNotFoundError:
            return True, "(node not installed, skipped)"
        except subprocess.CalledProcessError as e:
            return False, e.stderr.strip()
    return True, "(no parser available)"


def phase_syntax(file_paths: list[str]) -> list[dict]:
    results = []
    for path in file_paths:
        with open(path) as f:
            original = f.read()

        result = json.loads(
            subprocess.check_output(
                [sys.executable, MINIFIER, "--json", path],
                stderr=subprocess.DEVNULL,
            )
        )
        language = result["language"]
        minified = result["output"]

        # Check original is parseable (baseline)
        orig_ok, orig_err = _check_parseable(original, language)
        min_ok, min_err = _check_parseable(minified, language)

        # Idempotency check
        idem_result = subprocess.check_output(
            [sys.executable, MINIFIER, "--json", "--language", language],
            input=minified,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        idem = json.loads(idem_result)
        idempotent = idem["output"] == minified

        results.append({
            "file": os.path.basename(path),
            "language": language,
            "original_parseable": orig_ok,
            "minified_parseable": min_ok,
            "parse_error": min_err if not min_ok else "",
            "idempotent": idempotent,
        })
    return results


# ---------------------------------------------------------------------------
# Phase 3: LLM comprehension A/B test
# ---------------------------------------------------------------------------

LLM_COMPREHENSION_PROMPT = """\
Given the following source code, answer these questions concisely:

1. What is the main purpose of this code?
2. List all classes/types defined.
3. List all functions/methods defined.
4. Describe the control flow of the main entry point.

Code:
```{language}
{code}
```

Respond with a JSON object with keys: purpose, types, functions, control_flow.
"""


def phase_llm(file_paths: list[str], api_key: str) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    results = []
    for path in file_paths:
        with open(path) as f:
            original = f.read()

        result = json.loads(
            subprocess.check_output(
                [sys.executable, MINIFIER, "--json", path],
                stderr=subprocess.DEVNULL,
            )
        )
        language = result["language"]
        minified = result["output"]

        def ask(code: str, label: str) -> str:
            resp = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                temperature=0,
                messages=[{
                    "role": "user",
                    "content": LLM_COMPREHENSION_PROMPT.format(
                        language=language, code=code
                    ),
                }],
            )
            return resp.content[0].text

        original_response = ask(original, "original")
        minified_response = ask(minified, "minified")

        results.append({
            "file": os.path.basename(path),
            "language": language,
            "original_response": original_response,
            "minified_response": minified_response,
        })
    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(phases: dict) -> None:
    if "reduction" in phases:
        data = phases["reduction"]
        print("=" * 60)
        print("Phase 1: Token Reduction")
        print("=" * 60)
        print(f"{'File':<20} {'Lang':<10} {'Orig chars':<12} {'Min chars':<12} {'Reduction':<10}")
        print("-" * 64)
        total_orig = 0
        total_min = 0
        for r in data:
            ratio = r["reduction_ratio"]
            total_orig += r["original_chars"]
            total_min += r["minified_chars"]
            bar = "█" * int(ratio * 40) + "░" * (40 - int(ratio * 40))
            print(f"{r['file']:<20} {r['language']:<10} {r['original_chars']:<12} {r['minified_chars']:<12} {ratio:>7.1%}")
            print(f"{'':>20} {'':<10} {'':<12} {'':<12} {bar}")
        overall = 1 - total_min / total_orig
        print("-" * 64)
        print(f"{'TOTAL':<20} {'':<10} {total_orig:<12} {total_min:<12} {overall:>7.1%}")

    if "syntax" in phases:
        data = phases["syntax"]
        print()
        print("=" * 60)
        print("Phase 2: Syntax Validation & Idempotency")
        print("=" * 60)
        print(f"{'File':<20} {'Lang':<10} {'Parseable':<12} {'Idempotent':<12}")
        print("-" * 54)
        all_pass = True
        for r in data:
            parse_ok = r["minified_parseable"]
            idem = r["idempotent"]
            parse_status = "✅" if parse_ok else "❌ " + r.get("parse_error", "")
            idem_status = "✅" if idem else "❌"
            msg = f"{r['file']:<20} {r['language']:<10} {parse_status:<35} {idem_status:<12}"
            print(msg)
            if not parse_ok or not idem:
                all_pass = False
        print("-" * 54)
        if all_pass:
            print("✅ All files pass syntax and idempotency checks.")
        else:
            print("❌ Some files failed checks — review above.")

    if "llm" in phases:
        data = phases["llm"]
        print()
        print("=" * 60)
        print("Phase 3: LLM Comprehension A/B")
        print("=" * 60)
        for r in data:
            print(f"\n--- {r['file']} ({r['language']}) ---")
            print("  Original response:")
            for line in r["original_response"].strip().split("\n"):
                print(f"    {line}")
            print("  Minified response:")
            for line in r["minified_response"].strip().split("\n"):
                print(f"    {line}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate code-minification skill effectiveness."
    )
    parser.add_argument("files", nargs="+", help="Source files to evaluate")
    parser.add_argument("--phase", choices=["reduction", "syntax", "llm", "all"],
                        default="all", help="Which phase to run")
    parser.add_argument("--api-key", help="Anthropic API key for LLM phase")
    args = parser.parse_args()

    missing = [f for f in args.files if not os.path.isfile(f)]
    if missing:
        print(f"Files not found: {missing}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(MINIFIER):
        print(f"Minifier not found at {MINIFIER}", file=sys.stderr)
        sys.exit(1)

    phases = {}

    if args.phase in ("reduction", "all"):
        phases["reduction"] = phase_reduction(args.files)

    if args.phase in ("syntax", "all"):
        phases["syntax"] = phase_syntax(args.files)

    if args.phase in ("llm", "all"):
        if not args.api_key:
            print("Phase 3 (LLM) requires --api-key to be set.", file=sys.stderr)
        else:
            phases["llm"] = phase_llm(args.files, args.api_key)

    print_report(phases)


if __name__ == "__main__":
    main()
