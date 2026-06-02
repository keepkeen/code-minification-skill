---
name: code-minification
description: Read-only exploration of large source files when token budget is tight. Reduces tokens 10-35% by stripping comments and formatting noise.
when_to_use: "Explore large files cheaply. Save tokens. Slim down code before LLM analysis. Works when the agent has no native read_minified_file. Not for debugging, code review, or line-number-sensitive edits."
argument-hint: "[--keep-comments] [--json] [--language go]"
allowed-tools: Bash(python3 minify_code.py *)
compatibility: opencode, claude-code, codex
license: MIT
metadata:
  languages: "python,javascript,typescript,go,rust,java,c,cpp,csharp,swift,ruby,shell"
  token_reduction: "10-35% typical, higher on some Python files"
---

# Code Minification for LLM

Strip comments and formatting noise from source code before feeding it to the LLM, reducing token consumption while preserving the code's semantic skeleton for exploration.

This standalone skill is a conservative stdlib Python implementation. It uses `tokenize` for Python and lexical scanners for C-style and Ruby-style comments so comment markers inside strings, raw strings, template literals, and common regex literals are preserved. It is not the same as vix's native Tree-sitter virtual filesystem.

## When to Use

- **Exploring a new codebase** — reading many files to build a mental model of unfamiliar code
- **Large files** (100+ lines) — reducing file reads by up to 50% token savings
- **Token budget constrained** — when the context window is approaching its limit
- **Read-only understanding** — tasks where you just need to understand code structure, not edit with line-number precision
- **Cost-sensitive sessions** — evaluating across many files where every token costs money

## When NOT to Use (Critical Risks)

| Risk Scenario | Why It Fails |
|---|---|
| **Compile error debugging** | Compiler/linter error lines point to original file; minified version has wrong line numbers |
| **Stack trace analysis** | Trace file:line references are useless against minified output |
| **git diff / code review** | git diff output is in original format — mismatches minified view |
| **bash + grep mixed with minified files** | bash returns raw formatted code; read_minified_file returns compressed version. **LLM sees two inconsistent views of the same file.** |
| **Python / YAML / Nim** | Indentation is syntax, not formatting. Python is handled with `tokenize`; YAML/Nim are not supported |
| **Custom DSLs or unknown extensions** | The script cannot infer semantics for unsupported formats |
| **Line-number-sensitive edits** | Minified output has different line offsets; validate against raw source before editing |

## How It Works (Conceptual)

```
Source file
    │
    ▼
┌─────────────────────────────┐
│ Tokenize / lexical scan     │
│ (stdlib, no dependencies)   │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Preserve protected spans    │
│ strings, raw strings, regex │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Strip comments outside      │
│ protected spans             │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Normalize layout outside    │
│ protected spans             │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Optional evaluation         │
│ parser checks when present  │
└──────────┬──────────────────┘
           ▼
    Minified output
```

## Resource Tool: `minify_code.py`

A companion Python script at the same path as this SKILL.md. Pure stdlib, no pip install.

Agents run from the project directory, not the skill directory. Always resolve the path:

```bash
# Claude Code / opencode (automatic):
python3 "${CLAUDE_SKILL_DIR:-$HOME/.agents/skills/code-minification}/minify_code.py" path/to/file.py
```

### Usage

```bash
# Minify a single file
python3 minify_code.py path/to/file.py

# Keep comments
python3 minify_code.py --keep-comments path/to/file.go

# Pipe from stdin
cat file.ts | python3 minify_code.py --language typescript

# JSON output (for programmatic consumption)
python3 minify_code.py --json path/to/file.rs
```

### Input

| Argument | Description |
|---|---|
| `path` (positional) | Source file path. Language auto-detected from extension |
| `--language` / `-l` | Force language (python, javascript, go, rust, java, cpp, csharp, swift, ruby) |
| `--keep-comments` / `-k` | Preserve comments in output (default: strip) |
| `--json` / `-j` | Output JSON with original/minified token counts and ratio |
| stdin | Pipe code in, requires `--language` |

### Output

Normal mode: minified source code as stdout text.

JSON mode (`--json`):
```json
{
  "language": "python",
  "original_chars": 12500,
  "minified_chars": 7200,
  "reduction_ratio": 0.424,
  "comments_stripped": true,
  "output": "class Foo:\n def bar(self):\n  return 42"
}
```

### Supported Languages

| Extension | Language | Strategy |
|---|---|---|
| `.py` | Python | builtin `tokenize` module (indentation-aware) |
| `.js`, `.mjs`, `.cjs` | JavaScript | lexical comment strip; preserves strings/templates/common regex literals |
| `.ts` | TypeScript | lexical comment strip; parser validation skipped unless an external TS parser is available |
| `.jsx`, `.tsx` | React | lexical comment strip; JSX parser validation skipped |
| `.go` | Go | lexical comment strip; preserves line boundaries for correctness |
| `.rs` | Rust | lexical comment strip; preserves common raw strings and nested block comments; optional `rustc` validation |
| `.java` | Java | lexical comment strip |
| `.c`, `.h` | C | lexical comment strip; optional `clang` validation |
| `.cpp`, `.hpp`, `.cc` | C++ | lexical comment strip; optional `clang++ -std=c++20` validation |
| `.cs` | C# | lexical comment strip |
| `.swift` | Swift | lexical comment strip; preserves multiline string literals and nested block comments; optional `swiftc -parse` validation |
| `.rb` | Ruby | lexical hash-comment strip; preserves quoted strings |
| `.sh`, `.bash` | Shell | preserves newlines, collapses blank lines |

## Common Mistakes

| Mistake | Fix |
|---|---|
| Using minified output to match bash/grep results | Use raw `read_file` when you need to cross-reference with bash output |
| Writing minified code back without a formatter | Prefer raw edit tools; if writing minified code, run the language formatter and tests |
| Ignoring the syntax validation step | Run `evaluate.py --phase=syntax` when you intend to trust minified output |
| Assuming uniform compression across languages | Compression varies; shell scripts may barely shrink while Python can shrink heavily |
| Using minified reads for tasks requiring line numbers | Debug, lint, review tasks: use raw reads. Explore tasks: use minified reads |

## Anti-Patterns

- **Don't minify then edit without formatter round-trip** — the result stays compressed and breaks human workflow
- **Don't mix minified and raw views of the same file in one session** — it confuses the LLM's mental model
- **Don't apply minification to configuration files** — JSON, YAML, TOML don't benefit and may break

## Red Flags — Stop and Switch to Raw Read

- You're investigating a compile error or test failure with line numbers
- You ran `grep -n` or `git diff` and need to correlate results
- The file is a configuration format (JSON, YAML, TOML, INI)
- You need to count lines or reference specific line offsets
- The LLM is producing edits that don't match the expected output

