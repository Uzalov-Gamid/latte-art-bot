import tempfile
import unittest
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from models import Base, User, Submission, Evaluation, SubmissionStatus
from utils import calculate_average_scores, update_submission_scores, export_to_excel


class ScoringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.user = User(telegram_id=1, nickname="participant", points=0, evaluated_submissions_count=0)
        self.admin = User(telegram_id=2, nickname="judge", is_admin=True)
        self.submission = Submission(user=self.user, photo_file_id="photo")
        self.session.add_all([self.user, self.admin, self.submission])
        await self.session.flush()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def evaluation(self, visual=0, creativity=5, technique=5, harmony=5):
        result = Evaluation(submission_id=self.submission.id, admin_id=self.admin.id,
                            visual_quality=visual, creativity=creativity,
                            technical_skills=technique, overall_harmony=harmony,
                            total_score=visual+creativity+technique+harmony)
        self.session.add(result)
        await self.session.flush()
        return result

    async def test_zero_visual_does_not_discard_other_scores(self):
        await self.evaluation()
        result = await calculate_average_scores(self.session, self.submission.id)
        self.assertEqual(result["visual_quality"], 0)
        self.assertEqual(result["total_score"], 15)

    async def test_recalculation_does_not_double_credit_points(self):
        evaluation = await self.evaluation(visual=5)
        await update_submission_scores(self.session, self.submission.id)
        await update_submission_scores(self.session, self.submission.id)
        self.assertEqual(self.user.points, 20)
        self.assertEqual(self.user.evaluated_submissions_count, 1)
        evaluation.total_score = 24
        await self.session.flush()
        await update_submission_scores(self.session, self.submission.id)
        self.assertEqual(self.user.points, 24)
        self.assertEqual(self.user.evaluated_submissions_count, 1)

    async def test_rejecting_accepted_result_reverses_credit_once(self):
        from utils import apply_submission_result
        await self.evaluation(visual=5)
        await update_submission_scores(self.session, self.submission.id)
        apply_submission_result(self.submission, {}, accepted=False)
        apply_submission_result(self.submission, {}, accepted=False)
        self.assertEqual(self.user.points, 0)
        self.assertEqual(self.user.evaluated_submissions_count, 0)
        self.assertEqual(self.submission.status, SubmissionStatus.REJECTED)
