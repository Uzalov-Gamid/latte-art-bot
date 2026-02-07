"""
Тесты утилит: уровни, лимиты, экспорт.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from utils import (
    calculate_level_from_score,
    recalc_user_level_by_points,
)


class TestLevels(unittest.TestCase):
    """Тесты расчёта уровней."""

    def test_score_to_level_white(self):
        for s in (0, 5, 10):
            self.assertEqual(calculate_level_from_score(float(s)).value, "White")

    def test_score_to_level_orange(self):
        for s in (11, 15, 18):
            self.assertEqual(calculate_level_from_score(float(s)).value, "Orange")

    def test_score_to_level_green(self):
        for s in (19, 22, 25):
            self.assertEqual(calculate_level_from_score(float(s)).value, "Green")

    def test_score_to_level_red(self):
        for s in (26, 29, 32):
            self.assertEqual(calculate_level_from_score(float(s)).value, "Red")

    def test_score_to_level_black(self):
        for s in (33, 35, 38):
            self.assertEqual(calculate_level_from_score(float(s)).value, "Black")

    def test_score_to_level_gold(self):
        for s in (39, 40):
            self.assertEqual(calculate_level_from_score(float(s)).value, "Gold")

    def test_user_level_by_points(self):
        self.assertEqual(recalc_user_level_by_points(0).value, "White")
        self.assertEqual(recalc_user_level_by_points(10).value, "White")
        self.assertEqual(recalc_user_level_by_points(11).value, "Orange")
        self.assertEqual(recalc_user_level_by_points(19).value, "Green")
        self.assertEqual(recalc_user_level_by_points(26).value, "Red")
        self.assertEqual(recalc_user_level_by_points(33).value, "Black")
        self.assertEqual(recalc_user_level_by_points(39).value, "Gold")


if __name__ == "__main__":
    unittest.main()
