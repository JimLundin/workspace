"""Check the Liquid Glass kit's structure: every component is wired into both entry files, in tier order.

Run from anywhere: python design/liquid-glass/tools/check_structure.py
Exits non-zero and names each problem when the structure drifts.
"""

import re
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
TIERS = ("foundations", "atoms", "controls", "molecules", "containers", "bars")


def main() -> int:
    problems: list[str] = []
    css_entry = (KIT / "liquid-glass.css").read_text(encoding="utf-8")
    js_entry = (KIT / "liquid-glass.js").read_text(encoding="utf-8")

    declared = re.search(r"@layer\s+([^;]+);", css_entry)
    expected_layers = ", ".join(f"lg.{tier}" for tier in TIERS)
    if not declared or declared.group(1).strip() != expected_layers:
        problems.append(f"liquid-glass.css must declare the layers in tier order: @layer {expected_layers};")

    imports = re.findall(r"@import url\(([^)]+)\) layer\(lg\.([a-z]+)\);", css_entry)
    scripts = re.findall(r'"([a-z]+/[a-z-]+\.js)"', js_entry)

    for path, layer in imports:
        tier = path.split("/")[0]
        if tier != layer:
            problems.append(f"{path} is imported into lg.{layer}, but its folder is {tier}")
        if not (KIT / path).is_file():
            problems.append(f"liquid-glass.css imports {path}, which doesn't exist")
    for path in scripts:
        if not (KIT / path).is_file():
            problems.append(f"liquid-glass.js loads {path}, which doesn't exist")

    imported, loaded = {p for p, _ in imports}, set(scripts)
    for tier in TIERS:
        for file in sorted((KIT / tier).glob("*")):
            relative = f"{tier}/{file.name}"
            if file.suffix == ".css" and relative not in imported:
                problems.append(f"{relative} isn't imported in liquid-glass.css")
            if file.suffix == ".js" and relative not in loaded:
                problems.append(f"{relative} isn't loaded by liquid-glass.js")

    # Files must appear tier by tier, so each one only uses what earlier tiers define.
    for label, paths in (("liquid-glass.css", [p for p, _ in imports]), ("liquid-glass.js", [p for p in scripts if p.split("/")[0] in TIERS])):
        ranks = [TIERS.index(p.split("/")[0]) for p in paths]
        if ranks != sorted(ranks):
            problems.append(f"{label} lists components out of tier order")

    # Kit stylesheets style elements and attributes; any class they use is lg- prefixed.
    for tier in TIERS:
        for sheet in sorted((KIT / tier).glob("*.css")):
            text = re.sub(r"/\*.*?\*/", "", sheet.read_text(encoding="utf-8"), flags=re.S)
            selectors = " ".join(re.findall(r"([^{}]+)\{", text))
            for name in sorted(set(re.findall(r"(?<![\w-])\.([a-zA-Z][\w-]*)", selectors)) - {"woff2"}):
                if not name.startswith("lg-"):
                    problems.append(f"{tier}/{sheet.name} uses the unprefixed class .{name}")

    for problem in problems:
        print(problem)
    if not problems:
        print(f"Liquid Glass kit structure is consistent: {len(imports)} stylesheets, {len(scripts)} scripts.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
