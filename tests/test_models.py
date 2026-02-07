"""
Тесты моделей БД.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from models import UserLevel, SubmissionStatus, ChallengeStatus, User


class TestEnums(unittest.TestCase):
    """Тесты enum-значений."""

    def test_user_levels(self):
        self.assertEqual(UserLevel.WHITE.value, "White")
        self.assertEqual(UserLevel.GOLD.value, "Gold")

    def test_submission_statuses(self):
        self.assertEqual(SubmissionStatus.PENDING.value, "pending")
        self.assertEqual(SubmissionStatus.EVALUATED.value, "evaluated")

    def test_challenge_statuses(self):
        self.assertEqual(ChallengeStatus.ACTIVE.value, "active")
        self.assertEqual(ChallengeStatus.COMPLETED.value, "completed")


class TestUserModel(unittest.TestCase):
    """Тесты модели User."""

    def test_user_repr(self):
        u = User(telegram_id=123, nickname="Test", level=UserLevel.WHITE)
        self.assertIn("123", repr(u))
        self.assertIn("Test", repr(u))


if __name__ == "__main__":
    unittest.main()
