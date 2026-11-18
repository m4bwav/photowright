"""Proof bars for phw 0.25.2: SVG lengths in percent.

- A `<rect width="100%" height="100%">` (lineart-trace writes one as its background) parses as the
  whole viewBox instead of crashing `vcheck` with "could not convert string to float: '100%'".
- Percent x/width resolve against the width, y/height against the height.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
from phw import vector  # noqa: E402


class PercentLengths(unittest.TestCase):
    def test_full_rect(self):
        doc = vector.parse_svg('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" '
                               'viewBox="0 0 400 300"><rect width="100%" height="100%" fill="#fff"/></svg>')
        sub = doc["shapes"][0]["subs"][0]
        self.assertEqual(sub["start"], (0.0, 0.0))
        self.assertEqual(sub["segs"][1][1], (400.0, 300.0))

    def test_axes(self):
        doc = vector.parse_svg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
                               '<rect x="10%" y="10%" width="50%" height="50%"/></svg>')
        sub = doc["shapes"][0]["subs"][0]
        self.assertEqual(sub["start"], (20.0, 10.0))
        self.assertEqual(sub["segs"][1][1], (120.0, 60.0))


if __name__ == "__main__":
    unittest.main()
