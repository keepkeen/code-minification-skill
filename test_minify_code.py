#!/usr/bin/env python3
"""Regression tests for standalone code minification."""

import unittest

import minify_code


class MinifyCodeTests(unittest.TestCase):
    def test_javascript_preserves_url_string_and_strips_comment(self):
        src = 'const url = "https://example.com/a"; // remove me\nconsole.log(url);\n'
        out = minify_code.minify(src, "javascript")
        self.assertIn('"https://example.com/a"', out)
        self.assertNotIn("remove me", out)

    def test_javascript_preserves_regex_character_class(self):
        src = "const r = /[//]/; // remove me\nconsole.log(r);\n"
        out = minify_code.minify(src, "javascript")
        self.assertIn("/[//]/", out)
        self.assertNotIn("remove me", out)

    def test_c_preserves_comment_like_string(self):
        src = '#include <stdio.h>\nint main(){ printf("/* not a comment */"); return 0; }\n'
        out = minify_code.minify(src, "c")
        self.assertIn('"/* not a comment */"', out)

    def test_go_preserves_url_string(self):
        src = 'package main\nimport "fmt"\nfunc main(){fmt.Println("https://example.com/a")}\n'
        out = minify_code.minify(src, "go")
        self.assertIn('"https://example.com/a"', out)

    def test_ruby_preserves_hash_string_and_strips_comment(self):
        src = 'x = "#not comment"\nputs x # remove me\n'
        out = minify_code.minify(src, "ruby")
        self.assertIn('"#not comment"', out)
        self.assertNotIn("remove me", out)

    def test_shell_preserves_hash_string(self):
        src = 'echo "#not comment"\n# remove me\necho ok\n'
        out = minify_code.minify(src, "shell")
        self.assertIn('"#not comment"', out)
        self.assertNotIn("remove me", out)

    def test_swift_strips_nested_block_comment(self):
        src = '/* outer /* inner */ end */\nlet value = "/* not comment */"\n'
        out = minify_code.minify(src, "swift")
        self.assertNotIn("end */", out)
        self.assertIn('"/* not comment */"', out)

    def test_rust_strips_nested_block_comment(self):
        src = '/* outer /* inner */ end */\nfn main(){println!("/* not comment */");}\n'
        out = minify_code.minify(src, "rust")
        self.assertNotIn("end */", out)
        self.assertIn('"/* not comment */"', out)


if __name__ == "__main__":
    unittest.main()
