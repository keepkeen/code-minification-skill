---
name: code-minification
description: Reduce token usage 10-35% by stripping comments and formatting noise from source code before reading. Use when exploring large files on a tight token budget. NOT for debugging, code review, stack traces, or line-sensitive edits.
when_to_use: "Reading large files. Exploring new codebase. Token budget tight. Context window near limit. NOT for: compile error debugging, stack trace analysis, git diff/code review, config files (JSON/YAML/TOML), or tasks needing precise line numbers."
argument-hint: "[path] [--keep-comments] [--language go]"
allowed-tools: Bash(python3 minify_code.py *)
compatibility: opencode, claude-code, codex
license: MIT
metadata:
  languages: python,javascript,typescript,go,rust,java,c,cpp,csharp,swift,ruby,shell
  token_reduction: 10-35%
---

# Code Minification

Strip comments and whitespace from source files before reading to save tokens. Pure Python stdlib, no dependencies.

## Usage

Replace `read_file path` with:

```bash
python3 "${CLAUDE_SKILL_DIR:-$HOME/.agents/skills/code-minification}/minify_code.py" path
```

Options: `--keep-comments` (preserve comments), `--language <lang>` (override auto-detect), `--json` (output token stats).

Pipe from stdin: `cat file.ts | python3 minify_code.py --language typescript`

## Supported Languages

`.py` `.js` `.ts` `.jsx` `.tsx` `.go` `.rs` `.java` `.c` `.h` `.cpp` `.cs` `.swift` `.rb` `.sh`

Python uses `tokenize` (indentation-safe). All others use lexical comment stripping with string/template/regex preservation.

## Anti-Patterns

- **Don't minify then edit** — minified output has wrong line offsets. Use raw `read_file` before edits.
- **Don't mix minified and raw views** of the same file in one session — inconsistent mental model.
- **Don't apply to config files** (JSON, YAML, TOML) — no benefit, may break.
- **Don't use for debug/review** — line numbers shift, grep results mismatch.
