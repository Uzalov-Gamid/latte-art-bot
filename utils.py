"""
Утилиты:
- лимиты на подачу работ
- уровни и пересчёт уровня
- экспорт в Excel
- расчёт победителей челленджа (используется планировщиком)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from models import User, Submission, Evaluation, UserLevel, SubmissionStatus

logger = logging.getLogger(__name__)


# Пороги уровней участника по сумме баллов (points).
# points = сумма баллов за принятые работы (0..40 за работу).
LEVEL_THRESHOLDS: dict[UserLevel, int] = {
    UserLevel.WHITE: 0,
    UserLevel.ORANGE: 11,
    UserLevel.GREEN: 19,
    UserLevel.RED: 26,
    UserLevel.BLACK: 33,
    UserLevel.GOLD: 39,
}

# Score to level mapping (for individual submissions)
SCORE_TO_LEVEL = {
    (0, 10): UserLevel.WHITE,
    (11, 18): UserLevel.ORANGE,
    (19, 25): UserLevel.GREEN,
    (26, 32): UserLevel.RED,
    (33, 38): UserLevel.BLACK,
    (39, 40): UserLevel.GOLD,
}


def calculate_level_from_score(score: float) -> UserLevel:
    """Calculate LAGS level from a submission score (0-40)."""
    if not 0 <= score <= 40:
        raise ValueError("Score must be between 0 and 40")
    # Lower bounds are inclusive; fractional scores stay below the next level.
    for (min_score, _), level in reversed(tuple(SCORE_TO_LEVEL.items())):
        if score >= min_score:
            return level
    return UserLevel.WHITE


def recalc_user_level_by_points(points: int) -> UserLevel:
    """Пересчёт уровня участника по сумме баллов."""
    # Важно: идём от верхнего к нижнему.
    if points >= LEVEL_THRESHOLDS[UserLevel.GOLD]:
        return UserLevel.GOLD
    if points >= LEVEL_THRESHOLDS[UserLevel.BLACK]:
        return UserLevel.BLACK
    if points >= LEVEL_THRESHOLDS[UserLevel.RED]:
        return UserLevel.RED
    if points >= LEVEL_THRESHOLDS[UserLevel.GREEN]:
        return UserLevel.GREEN
    if points >= LEVEL_THRESHOLDS[UserLevel.ORANGE]:
        return UserLevel.ORANGE
    return UserLevel.WHITE


def get_next_level_threshold(current_level: UserLevel) -> int:
    """Get points threshold for next level."""
    levels = [
        UserLevel.WHITE, UserLevel.ORANGE, UserLevel.GREEN,
        UserLevel.RED, UserLevel.BLACK, UserLevel.GOLD
    ]
    try:
        current_idx = levels.index(current_level)
        if current_idx < len(levels) - 1:
            return LEVEL_THRESHOLDS[levels[current_idx + 1]]
    except ValueError:
        pass
    return LEVEL_THRESHOLDS[UserLevel.GOLD]  # Max level


async def check_submission_limit(session: AsyncSession, user_id: int, weeks: int = 1) -> tuple[bool, int]:
    """
    Check if user has exceeded submission limit (default: 3 per week).
    Returns (can_submit, count_this_week).
    """
    limit = 3
    week_ago = datetime.utcnow() - timedelta(weeks=weeks)

    result = await session.execute(
        select(func.count(Submission.id))
        .where(Submission.user_id == user_id)
        .where(Submission.submission_date >= week_ago)
    )
    count = result.scalar() or 0
    return count < limit, count


async def get_user_ranking(session: AsyncSession, user_id: int) -> int:
    """Get user's ranking position based on points."""
    user = await session.get(User, user_id)
    if not user:
        return 0

    result = await session.execute(
        select(func.count(User.id)).where(User.points > user.points)
    )
    rank = (result.scalar() or 0) + 1
    return rank


async def calculate_average_scores(session: AsyncSession, submission_id: int) -> Dict[str, float]:
    """
    Calculate average scores from all evaluations for a submission.
    Returns dict with visual_quality, creativity, technical_skills, overall_harmony, total_score.
    """
    result = await session.execute(
        select(
            func.avg(Evaluation.visual_quality).label('visual'),
            func.avg(Evaluation.creativity).label('creativity'),
            func.avg(Evaluation.technical_skills).label('technical'),
            func.avg(Evaluation.overall_harmony).label('harmony'),
            func.avg(Evaluation.total_score).label('total')
        )
        .where(Evaluation.submission_id == submission_id)
    )
    row = result.first()

    if row and row.visual is not None:
        return {
            'visual_quality': round(row.visual, 2),
            'creativity': round(row.creativity, 2),
            'technical_skills': round(row.technical, 2),
            'overall_harmony': round(row.harmony, 2),
            'total_score': round(row.total, 2)
        }
    return {
        'visual_quality': 0.0,
        'creativity': 0.0,
        'technical_skills': 0.0,
        'overall_harmony': 0.0,
        'total_score': 0.0
    }


def apply_submission_result(submission, scores, accepted=True):
    """Replace a result and credit only its change to the participant."""
    was_evaluated = submission.status == SubmissionStatus.EVALUATED
    previous_points = int(submission.total_score or 0) if was_evaluated else 0
    if accepted:
        for field in ("visual_quality", "creativity", "technical_skills", "overall_harmony", "total_score"):
            setattr(submission, field, scores[field])
        submission.level_achieved = calculate_level_from_score(scores["total_score"])
        submission.status = SubmissionStatus.EVALUATED
    else:
        submission.status = SubmissionStatus.REJECTED
    new_points = int(submission.total_score or 0) if accepted else 0
    user = submission.user
    user.points = (user.points or 0) + new_points - previous_points
    user.evaluated_submissions_count = max(0, (user.evaluated_submissions_count or 0) + int(accepted) - int(was_evaluated))
    user.level = recalc_user_level_by_points(user.points)


async def update_submission_scores(session: AsyncSession, submission_id: int):
    """Update submission with averaged scores from all evaluations."""
    scores = await calculate_average_scores(session, submission_id)
    # Eagerly load the user relationship to avoid lazy loading issues
    result = await session.execute(
        select(Submission)
        .where(Submission.id == submission_id)
        .options(selectinload(Submission.user))
    )
    submission = result.scalar_one_or_none()

    count = await session.scalar(
        select(func.count(Evaluation.id)).where(Evaluation.submission_id == submission_id)
    )
    if submission and count:
        apply_submission_result(submission, scores)

        await session.commit()


async def export_to_excel(session: AsyncSession, filename: Optional[str] = None) -> str:
    """
    Export all data to Excel file with multiple sheets.
    Returns path to created file.
    """
    try:
        if filename is None:
            filename = f"latte_art_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        # Лист 1: Участники
        users_result = await session.execute(select(User).order_by(desc(User.points)))
        users = users_result.scalars().all()

        users_data = []
        for user in users:
            users_data.append({
                "ID": user.id,
                "Telegram ID": user.telegram_id,
                "Username": user.username or "",
                "Ник": user.nickname,
                "Город": user.city or "",
                "Кофейня": user.coffee_shop or "",
                "Уровень": user.level.value if hasattr(user.level, "value") else str(user.level),
                "Баллы": int(user.points or 0),
                "Работ отправлено": int(user.submissions_count or 0),
                "Работ оценено": int(user.evaluated_submissions_count or 0),
                "Дата регистрации": user.registration_date.strftime("%Y-%m-%d %H:%M") if user.registration_date else "",
                "Статус": "Участник",
                "Админ": "Да" if user.is_admin else "Нет",
            })

        df_users = pd.DataFrame(users_data)

        # Лист 2: Работы
        submissions_result = await session.execute(
            select(Submission)
            .order_by(desc(Submission.submission_date))
            .options(selectinload(Submission.user))
        )
        submissions = submissions_result.scalars().all()

        submissions_data = []
        for sub in submissions:
            level_val = sub.level_achieved.value if sub.level_achieved and hasattr(sub.level_achieved, "value") else ""
            submissions_data.append({
                "ID": sub.id,
                "Автор (Telegram ID)": sub.user.telegram_id if sub.user else "",
                "Автор Username": (sub.user.username or "") if sub.user else "",
                "Автор Ник": (sub.user.nickname or "") if sub.user else "",
                "Дата": sub.submission_date.strftime("%Y-%m-%d %H:%M") if sub.submission_date else "",
                "Описание": sub.description or "",
                "Визуал": int(sub.visual_quality or 0),
                "Креатив": int(sub.creativity or 0),
                "Техника": int(sub.technical_skills or 0),
                "Гармония": int(sub.overall_harmony or 0),
                "Итог": int(sub.total_score or 0),
                "Уровень": level_val,
                "Статус": sub.status.value if hasattr(sub.status, "value") else str(sub.status),
                "Комментарий": sub.admin_comment or "",
                "file_id фото": sub.photo_file_id,
            })

        df_submissions = pd.DataFrame(submissions_data)

        # Лист 3: Рейтинг (топ-100)
        leaderboard_result = await session.execute(
            select(User).order_by(desc(User.points))
            .limit(100)
        )
        leaderboard = leaderboard_result.scalars().all()

        leaderboard_data = []
        for idx, user in enumerate(leaderboard, 1):
            avg_score = 0.0
            if user.evaluated_submissions_count > 0:
                avg_score = user.points / user.evaluated_submissions_count

            leaderboard_data.append({
                "Место": idx,
                "Telegram ID": user.telegram_id,
                "Username": user.username or "",
                "Ник": user.nickname,
                "Город": user.city or "",
                "Уровень": user.level.value if hasattr(user.level, "value") else str(user.level),
                "Баллы": int(user.points or 0),
                "Оценено работ": int(user.evaluated_submissions_count or 0),
                "Средний балл": round(avg_score, 2),
            })

        df_leaderboard = pd.DataFrame(leaderboard_data)

        # Лист 4: Оценки (история)
        evaluations_result = await session.execute(
            select(Evaluation)
            .options(selectinload(Evaluation.submission).selectinload(Submission.user))
        )
        evaluations = evaluations_result.scalars().all()

        evaluations_data = []
        for ev in evaluations:
            admin = await session.get(User, ev.admin_id)
            evaluations_data.append({
                "ID": ev.id,
                "Submission ID": ev.submission_id,
                "Автор": ev.submission.user.nickname if ev.submission and ev.submission.user else "",
                "Visual": int(ev.visual_quality),
                "Creativity": int(ev.creativity),
                "Technique": int(ev.technical_skills),
                "Harmony": int(ev.overall_harmony),
                "Total": int(ev.total_score),
                "Комментарий": ev.comment or "",
                "Дата оценки": ev.evaluation_date.strftime("%Y-%m-%d %H:%M:%S") if ev.evaluation_date else "",
                "Админ": admin.nickname if admin else "",
            })

        df_evaluations = pd.DataFrame(evaluations_data)

        # Write to Excel
        with pd.ExcelWriter(filename, engine="openpyxl") as writer:
            df_users.to_excel(writer, sheet_name="Участники", index=False)
            df_submissions.to_excel(writer, sheet_name="Работы", index=False)
            df_leaderboard.to_excel(writer, sheet_name="Рейтинг", index=False)
            df_evaluations.to_excel(writer, sheet_name="Оценки", index=False)

        logger.info(f"Excel export created: {filename}")
        return filename

    except Exception as e:
        logger.error(f"Error exporting to Excel: {e}")
        raise


def get_localized_text(key: str, language: str = "ru") -> str:
    """Get localized text. Simple implementation - can be extended."""
    texts = {
        "ru": {
            "welcome": "Добро пожаловать в бот соревнований по латте-арту!",
            "profile": "Профиль",
            "submit": "Отправить работу",
            "leaderboard": "Рейтинг",
            "challenges": "Челленджи",
            "best_works": "Лучшие работы",
            "help": "Помощь",
        },
        "en": {
            "welcome": "Welcome to Latte Art Competition Bot!",
            "profile": "Profile",
            "submit": "Submit Work",
            "leaderboard": "Leaderboard",
            "challenges": "Challenges",
            "best_works": "Best Works",
            "help": "Help",
        }
    }
    return texts.get(language, texts["ru"]).get(key, key)


