"""Seeded mutation replacements reach the mutant exactly as written."""

from pathlib import Path

from scripts.mutate import Replacement, replacements, seeded

SOURCE = b'def outcome(ready):\n    if ready:\n        return "verified"\n    return "uncertain"\n'
SEEDS = """\
[[replacement]]
before = 'return "uncertain"'
after = 'return "verified"'

[[replacement]]
before = '''
    if ready:
        return "verified"'''
after = '''
    if not ready:
        return "verified"'''
"""


def test_replacements_file_seeds_quoted_and_multiline_fragments_exactly(tmp_path: Path) -> None:
    # Defect: the seeded path alters quotes or line breaks (as Windows command
    # lines did), so a campaign runs an unintended mutant such as a NameError.
    file = tmp_path / "seeds.toml"
    file.write_text(SEEDS, encoding="utf-8")
    assert [mutation.apply(SOURCE) for mutation in replacements(SOURCE, seeded(file))] == [
        b'def outcome(ready):\n    if ready:\n        return "verified"\n    return "verified"\n',
        b'def outcome(ready):\n    if not ready:\n        return "verified"\n    return "uncertain"\n',
    ]


def test_an_ambiguous_seed_is_refused_instead_of_mutating_its_first_match() -> None:
    # Defect: a fragment that occurs twice silently mutates whichever comes first.
    try:
        replacements(SOURCE, (Replacement("return", "yield"),))
    except ValueError:
        pass
    else:
        raise AssertionError("An ambiguous seed was accepted.")
