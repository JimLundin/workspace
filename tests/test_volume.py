from scripts.volume import code_lines, measure, measured, nodes


def test_volume_ignores_layout_comments_and_docstrings() -> None:
    # Defect: the measure counts tokens, lines or docstrings, so Ruff's wrapping or documentation moves it.
    dense = "class A:\n    def f(self, x): return [x, x + 1]\n"
    spread = '''"""Module."""


class A:
    """Class."""

    def f(self, x):
        """Method."""
        # A comment.
        return [
            x,
            x + 1,
        ]
'''
    assert nodes(dense) == nodes(spread)
    assert nodes(dense) < nodes(dense + "y = 1\n")


def test_page_scripts_count_their_tokens_but_not_their_layout_or_comments() -> None:
    # Defect: a script moved out of a Python string drops out of the total, or its comments and wrapping move it.
    dense = r"const f = (a, b) => a / b; s.replace(/\s+/g, ' ');"
    spread = "// Divide.\nconst f = (a, b) =>\n    a / b; /* then */\n" + r"s.replace(/\s+/g," + "\n  ' ');\n"
    # The regular expression and the string are one token each; the division is not a regular expression.
    assert measured("page.js", dense) == measured("page.js", spread) == 22
    assert measured("page.js", dense) < measured("page.js", dense + "f(1, 2);")


def test_code_lines_leave_out_blanks_comments_and_docstrings() -> None:
    # Defect: the report's line column counts documentation or layout, so a comment moves it.
    source = '"""Module."""\n\n# A comment.\ndef f(x):\n    """Doc\n    string."""\n    return [\n        x,\n    ]\n'
    assert code_lines(source) == 4
    assert measure("page.js", "// note\nconst a = 1;\n\n/* block */ f(a);\n").lines == 2
