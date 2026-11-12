"""Relative links and images in the Markdown docs must point at files that exist."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# [text](url) and ![alt](url); also HTML src/href used in the main README badges.
MD_LINK = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_ATTR = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", re.I)
FENCE = re.compile(r"^```")


def _skip(url: str) -> bool:
    u = url.strip()
    if not u or u.startswith(("#", "mailto:", "http://", "https://", "data:", "//")):
        return True
    return False


def _local_target(base: Path, url: str) -> Path:
    path = url.split("#", 1)[0].split("?", 1)[0]
    return (base.parent / path).resolve()


def markdown_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "LEARN.md"]
    files.extend(sorted(ROOT.glob("0*/README.md")))
    return [p for p in files if p.is_file()]


def extract_local_links(path: Path) -> list[tuple[str, Path]]:
    text = path.read_text(encoding="utf-8")
    urls: list[str] = []
    # Ignore fenced code so sample CLI paths are not treated as links.
    visible = []
    fencing = False
    for line in text.splitlines():
        if line.startswith("```"):
            fencing = not fencing
            continue
        if not fencing:
            visible.append(line)
    body = "\n".join(visible)
    for m in MD_LINK.finditer(body):
        urls.append(m.group(1) or m.group(2))
    for m in HTML_ATTR.finditer(body):
        urls.append(m.group(1))
    out = []
    for url in urls:
        if _skip(url):
            continue
        out.append((url, _local_target(path, url)))
    return out


class TestReadmeLinks(unittest.TestCase):
    def test_relative_links_resolve(self):
        checked = 0
        for md in markdown_files():
            for url, target in extract_local_links(md):
                checked += 1
                with self.subTest(file=str(md.relative_to(ROOT)), url=url):
                    self.assertTrue(
                        target.exists(),
                        f"{md.relative_to(ROOT)} links to {url} -> {target} (missing)",
                    )
                    # Directory links like 01-vlan-trunk/ are allowed.
                    if target.is_file():
                        self.assertGreater(target.stat().st_size, 0)
        self.assertGreaterEqual(checked, 10, "expected the main README to have local lab/screenshot links")

    def test_main_readme_points_at_every_lab(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for lab in ("01-vlan-trunk", "02-inter-vlan", "03-ospf", "04-acl"):
            with self.subTest(lab=lab):
                self.assertIn(f"{lab}/", readme)
                self.assertIn(f"docs/screenshots/{lab}.png", readme)

    def test_markdown_fences_are_balanced(self):
        for md in markdown_files():
            with self.subTest(file=str(md.relative_to(ROOT))):
                fences = sum(1 for line in md.read_text(encoding="utf-8").splitlines() if line.startswith("```"))
                self.assertEqual(fences % 2, 0, f"{md.name} has an unclosed code fence")


if __name__ == "__main__":
    unittest.main()
