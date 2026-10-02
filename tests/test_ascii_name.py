from __future__ import annotations

import io
import unicodedata
import unittest
import xml.etree.ElementTree as ET

from PIL import Image

from renderers.ascii import _name_masks, _split_name, render_ascii_name
from renderers.header import render_profile_svg
from services.github import GitHubProfile


class AsciiNameTests(unittest.TestCase):
    def test_vietnamese_name_has_dense_readable_glyphs(self) -> None:
        group = ET.fromstring(render_ascii_name("Nguyễn Phương Gia Bảo", "#172f4a"))
        cells = group.findall("text")
        # The former clipped tile left only a few scattered marks in the letters.
        self.assertGreater(len(cells), 900)
        self.assertGreater(sum(cell.text == "#" for cell in cells), 500)
        self.assertLessEqual(max(float(cell.attrib["x"]) for cell in cells) + 3, 570)
        self.assertLessEqual(max(float(cell.attrib["y"]) for cell in cells), 339)

    def test_existing_name_line_breaks_are_preserved(self) -> None:
        self.assertEqual(_split_name("Nguyễn Phương Gia Bảo"), ["Nguyễn Phương", "Gia Bảo"])

    def test_unicode_forms_render_identically(self) -> None:
        name = "Nguyễn Phương Gia Bảo"
        self.assertEqual(render_ascii_name(name, "#fff"), render_ascii_name(unicodedata.normalize("NFD", name), "#fff"))

    def test_long_name_stays_inside_the_header(self) -> None:
        cells = ET.fromstring(render_ascii_name("Alexandria " * 12, "#fff")).findall("text")
        self.assertTrue(cells)
        self.assertLessEqual(max(float(cell.attrib["x"]) for cell in cells) + 3, 570)
        self.assertLessEqual(max(float(cell.attrib["y"]) for cell in cells), 339)

    def test_short_and_empty_names_are_visible(self) -> None:
        for name in ("A", "", "   "):
            with self.subTest(name=name):
                self.assertTrue(ET.fromstring(render_ascii_name(name, "#fff")).findall("text"))

    def test_accents_have_distinct_letter_shapes(self) -> None:
        accent_mask = _name_masks("Bảo")[0]
        plain_mask = _name_masks("Bao")[0]
        self.assertNotEqual((accent_mask.size, accent_mask.tobytes()), (plain_mask.size, plain_mask.tobytes()))

    def test_both_themes_are_valid_svg_with_accessible_name(self) -> None:
        profile = GitHubProfile("test", "Nguyễn & <Bảo>", "", "Hồ Chí Minh", 14, 2)
        avatar = io.BytesIO()
        Image.new("RGB", (66, 52), (100, 150, 200)).save(avatar, format="PNG")
        ns = {"svg": "http://www.w3.org/2000/svg"}
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                svg = render_profile_svg(profile=profile, avatar_bytes=avatar.getvalue(), theme=theme, config={})
                tree = ET.fromstring(svg)
                title = tree.find("svg:title", ns)
                assert title is not None
                self.assertEqual(title.text, profile.name + " — ASCII identity")
                group = tree.find("svg:g[@class='name']", ns)
                assert group is not None
                self.assertGreater(len(group.findall(".//svg:text", ns)), 500)
                self.assertNotIn('url(#name-ascii)', svg)
                self.assertIn('prefers-reduced-motion', svg)


if __name__ == "__main__":
    unittest.main()
