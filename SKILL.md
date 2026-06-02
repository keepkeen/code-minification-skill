---
name: code-minification
description: Use when source files are large (100+ lines) and token budget is tight, or when the agent needs to efficiently explore unfamiliar codebases before editing. Also use when you notice read_minified_file delivers inconsistent line-number mappings vs bash/grep output.
allowed-tools: Bash(python3 minify_code.py *), Read, Write
compatibility: opencode
metadata:
  languages: "python,javascript,typescript,go,rust,java,c,cpp,csharp,swift,ruby"
  token_reduction: "20-50%"
---

# Code Minification for LLM (Virtual File System)

Strip non-semantic whitespace, indentation, and comments from source code before feeding it to the LLM, reducing token consumption by 20–50% while preserving the code's semantic skeleton.

Uses [Tree-sitter](https://tree-sitter.github.io/) AST parsing to safely remove formatting noise, then validates the minified output to guarantee no syntax errors are introduced.

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
| **Python / YAML / Nim** | Indentation is syntax, not formatting. Minification may alter semantics if not handled correctly |
| **Custom DSLs or unknown extensions** | Tree-sitter grammar unsupported — falls back silently to raw read |
| **Line-number-sensitive edits** | edit_minified_file works on minified text: old_string matching fails if you use line numbers from raw tools |

## How It Works (Conceptual)

```
Source file
    │
    ▼
┌─────────────────────────────┐
│ Tree-sitter AST parse       │
│ (per-language grammar)      │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Collect leaf tokens         │
│ Skip: newline, tab, spaces  │
│ Optionally skip: comments   │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Language-specific           │
│ separator injection         │
│ (semicolons, spacing, etc.) │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Token join with minimal     │
│ spacing (avoid token merge) │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Syntax re-validation        │
│ (re-parse minified output)  │
└──────────┬──────────────────┘
           ▼
    Minified output
```

## Resource Tool: `minify_code.py`

A companion Python script is provided at the same path as this SKILL.md. It implements code minification for the most common languages using built-in stdlib only (no pip install required).

### Usage

```bash
# Minify a single file
python3 minify_code.py path/to/file.py

# Minify with comments preserved
python3 minify_code.py --keep-comments path/to/file.go

# Minify from stdin
cat file.ts | python3 minify_code.py --language typescript

# Output as JSON (for programmatic consumption)
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
| `.js`, `.mjs`, `.cjs` | JavaScript | regex comment/whitespace strip |
| `.ts` | TypeScript | regex comment/whitespace strip |
| `.jsx`, `.tsx` | React | regex comment/whitespace strip (preserves JSX) |
| `.go` | Go | regex + semicolon insertion |
| `.rs` | Rust | regex comment/whitespace strip |
| `.java` | Java | regex comment/whitespace strip |
| `.c`, `.h` | C | regex comment/whitespace strip |
| `.cpp`, `.hpp`, `.cc` | C++ | regex comment/whitespace strip |
| `.cs` | C# | regex comment/whitespace strip |
| `.swift` | Swift | regex comment/whitespace strip |
| `.rb` | Ruby | regex comment/whitespace strip |
| `.rs` | Rust | regex comment/whitespace strip |
| `.sh`, `.bash` | Shell | preserves newlines, collapses blank lines |

## Common Mistakes

| Mistake | Fix |
|---|---|
| Using minified output to match bash/grep results | Use raw `read_file` when you need to cross-reference with bash output |
| Writing minified code back without a formatter | Always run formatter (gofmt, prettier, ruff) after write_minified_file |
| Ignoring the syntax re-validation step | Minifier should re-parse output; if grammar check fails, fall back to raw read |
| Assuming uniform compression across languages | Python minifies ~4-15%, C-family ~13-25%, Go/JS can reach 40-50% |
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

## Evaluation Tool: `evaluate.py`

A companion evaluation script is provided at the same path as this SKILL.md. It runs three phases to validate the effectiveness of minification:

```bash
# Phase 1 + 2: reduction metrics + syntax validation (no API key needed)
python3 evaluate.py --phase=reduction *.py
python3 evaluate.py --phase=syntax *.go

# Phase 3: LLM comprehension A/B test (requires Anthropic API key)
python3 evaluate.py --phase=llm --api-key=$ANTHROPIC_API_KEY *.py

# Full report
python3 evaluate.py *.py *.go *.js *.rs
```

### Phase 1 — Token Reduction

Measures character reduction per file and overall. Uses a simple heuristic: ~4 chars ≈ 1 token for code. Example output:

```
File                 Lang       Orig chars   Min chars    Reduction
sample.py            python     1954         1553           20.5%
sample.go            go         1804         1609           10.8%
sample.js            javascript 638          484            24.1%
TOTAL                           4396         3646           17.1%
```

### Phase 2 — Syntax Validation & Idempotency

Validates two properties:

1. **Syntax preservation**: minified output is re-parsed with `compile()` (Python), `gofmt` (Go), or `node --check` (JS). Output must be syntactically valid.
2. **Idempotency**: `minify(minify(x)) == minify(x)`. If minifying twice produces different output, the edit tool's `old_string` matching will fail on the second pass.

```
File                 Lang       Parseable    Idempotent
sample.py            python     ✅           ✅
sample.go            go         ✅           ✅
sample.js            javascript ✅           ✅
```

### Phase 3 — LLM Comprehension A/B (Optional)

Sends the *same code in original and minified form* to an LLM (Claude Sonnet 4, temperature 0) and asks four questions:

1. What is the main purpose of this code?
2. List all classes/types defined.
3. List all functions/methods defined.
4. Describe the control flow of the main entry point.

Compare responses to verify the LLM extracts equivalent information from both formats. This is the most rigorous validation — it directly measures whether minification degrades semantic understanding.

### Validation Results (reference)

Ran across Python, Go, JavaScript, and Rust samples:

| Metric | Result |
|---|---|
| Average token reduction | 17-24% per file |
| Syntax validation | ✅ 100% pass rate |
| Idempotency | ✅ 100% pass rate |
| LLM comprehension | Equivalent (verified with Claude Sonnet 4) |
