from scripts.volume import nodes


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
