"""
Роутер админа:
- /admin_login (FSM + попытки + блокировка 5 минут)
- /admin_menu
- оценка работ (LAGS 0-10 по 4 критериям + комментарий + статус)
- экспорт в Excel (/export excel)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import AdminSession, Evaluation, Submission, SubmissionStatus, User
from utils import calculate_level_from_score, export_to_excel, recalc_user_level_by_points

logger = logging.getLogger(__name__)

router = Router()


class AdminLoginFSM(StatesGroup):
    waiting_password = State()


class JudgeFSM(StatesGroup):
    scoring_visual = State()
    scoring_creativity = State()
    scoring_technique = State()
    scoring_harmony = State()
    waiting_comment = State()
    waiting_decision = State()


def _escape_html(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="a:cancel")]]
    )


def admin_menu_kb(pending_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"⚖️ Оценить работы ({pending_count})", callback_data="a:judge")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="a:stats")],
            [InlineKeyboardButton(text="👥 Участники", callback_data="a:users")],
            [InlineKeyboardButton(text="📥 Экспорт Excel", callback_data="a:export_excel")],
            [InlineKeyboardButton(text="🚪 Выйти", callback_data="a:logout")],
        ]
    )


def score_kb(prefix: str) -> InlineKeyboardMarkup:
    # 0..10 в две строки, чтобы не было слишком широко
    row1 = [InlineKeyboardButton(text=str(i), callback_data=f"{prefix}:{i}") for i in range(0, 6)]
    row2 = [InlineKeyboardButton(text=str(i), callback_data=f"{prefix}:{i}") for i in range(6, 11)]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


def decision_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data="a:decide:accept"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data="a:decide:reject"),
            ]
        ]
    )


async def get_user_by_tg(session: AsyncSession, telegram_id: int) -> Optional[User]:
    res = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return res.scalar_one_or_none()


async def require_admin(session: AsyncSession, telegram_id: int, reply_to: Message) -> bool:
    """
    Проверка прав админа.

    Важно: для CallbackQuery нельзя использовать reply_to.from_user.id,
    потому что reply_to (cb.message) "от имени бота". Нужно передавать
    telegram_id = cb.from_user.id.
    """
    user = await get_user_by_tg(session, telegram_id)
    if not user or not user.is_admin:
        await reply_to.answer("Нужна авторизация: /admin_login")
        return False
    return True


async def get_admin_session(session: AsyncSession, telegram_id: int) -> AdminSession:
    res = await session.execute(select(AdminSession).where(AdminSession.telegram_id == telegram_id))
    s = res.scalar_one_or_none()
    if s:
        return s
    s = AdminSession(telegram_id=telegram_id, is_logged_in=False, login_attempts=0, last_attempt=None)
    session.add(s)
    await session.commit()
    return s


def _is_bcrypt_hash(value: str) -> bool:
    return value.startswith("$2a$") or value.startswith("$2b$") or value.startswith("$2y$")


def _check_admin_password(plain: str, env_value: str) -> bool:
    """
    Поддержка двух режимов:
    - ADMIN_PASSWORD содержит bcrypt-хэш -> проверяем bcrypt
    - ADMIN_PASSWORD содержит обычный пароль -> сравниваем как есть (для совместимости)
    """
    if not env_value:
        return False
    if _is_bcrypt_hash(env_value):
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), env_value.encode("utf-8"))
        except Exception:
            return False
    return plain == env_value


@router.message(Command("admin_login"))
async def admin_login_cmd(message: Message, session: AsyncSession, state: FSMContext) -> None:
    admin_session = await get_admin_session(session, message.from_user.id)
    if admin_session.login_attempts >= 3 and admin_session.last_attempt:
        if datetime.utcnow() - admin_session.last_attempt < timedelta(minutes=5):
            await message.answer("Слишком много попыток. Подожди 5 минут.")
            return
        admin_session.login_attempts = 0
        await session.commit()

    await state.clear()
    attempts_left = max(0, 3 - (admin_session.login_attempts or 0))
    await message.answer(
        f"Вход в админ-панель\nВведи пароль (попыток осталось: {attempts_left})",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AdminLoginFSM.waiting_password)


@router.callback_query(F.data == "a:cancel")
async def admin_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.answer("Ок, отменил.")
    await cb.answer()


@router.message(AdminLoginFSM.waiting_password)
async def admin_login_password(message: Message, session: AsyncSession, state: FSMContext) -> None:
    env_pass = os.getenv("ADMIN_PASSWORD", "")
    admin_session = await get_admin_session(session, message.from_user.id)

    if admin_session.login_attempts >= 3 and admin_session.last_attempt:
        if datetime.utcnow() - admin_session.last_attempt < timedelta(minutes=5):
            await message.answer("Слишком много попыток. Подожди 5 минут.")
            await state.clear()
            return
        admin_session.login_attempts = 0
        await session.commit()

    ok = _check_admin_password((message.text or "").strip(), env_pass)
    if not ok:
        admin_session.login_attempts = (admin_session.login_attempts or 0) + 1
        admin_session.last_attempt = datetime.utcnow()
        await session.commit()

        if admin_session.login_attempts >= 3:
            await message.answer("Слишком много попыток. Подожди 5 минут.")
            await state.clear()
            return

        attempts_left = 3 - admin_session.login_attempts
        await message.answer(f"Неверный пароль. Попыток осталось: {attempts_left}", reply_markup=cancel_kb())
        return

    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            nickname=message.from_user.full_name[:30] if message.from_user.full_name else "Admin",
            points=0,
            submissions_count=0,
            is_admin=True,
            is_banned=False,
            last_activity=datetime.utcnow(),
        )
        session.add(user)
    else:
        user.is_admin = True

    admin_session.is_logged_in = True
    admin_session.login_attempts = 0
    admin_session.last_attempt = None
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>Добро пожаловать в админ-панель!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Используй /admin_menu для управления.",
        parse_mode="HTML",
    )


@router.message(Command("admin_menu"))
async def admin_menu_cmd(message: Message, session: AsyncSession) -> None:
    if not await require_admin(session, message.from_user.id, message):
        return

    res = await session.execute(
        select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
    )
    pending_count = res.scalar() or 0
    text = (
        "🔧 <b>Админ-панель</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Выбери действие:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_menu_kb(pending_count))


@router.callback_query(F.data == "a:stats")
async def admin_stats_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await require_admin(session, cb.from_user.id, cb.message):
        await cb.answer()
        return

    users_count = await session.execute(select(func.count(User.id)))
    subs_count = await session.execute(select(func.count(Submission.id)))
    pending_count = await session.execute(
        select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
    )
    evaluated_count = await session.execute(
        select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.EVALUATED)
    )
    avg_result = await session.execute(
        select(func.avg(Submission.total_score)).where(Submission.status == SubmissionStatus.EVALUATED)
    )

    text = (
        "📊 <b>Статистика</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👥 Участников: <b>{users}</b>\n"
        "📸 Всего работ: <b>{subs}</b>\n"
        "⏳ На оценке: <b>{pending}</b>\n"
        "✅ Оценено: <b>{evaluated}</b>\n"
        "⭐ Средний балл: <b>{avg:.1f}</b>/40\n"
    ).format(
        users=users_count.scalar() or 0,
        subs=subs_count.scalar() or 0,
        pending=pending_count.scalar() or 0,
        evaluated=evaluated_count.scalar() or 0,
        avg=avg_result.scalar() or 0.0,
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="a:back")]])
    await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "a:back")
async def admin_back_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await require_admin(session, cb.from_user.id, cb.message):
        await cb.answer()
        return
    pending = (await session.execute(
        select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
    )).scalar() or 0
    await cb.message.answer(
        "🔧 <b>Админ-панель</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=admin_menu_kb(pending),
    )
    await cb.answer()


@router.callback_query(F.data == "a:users")
async def admin_users_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await require_admin(session, cb.from_user.id, cb.message):
        await cb.answer()
        return

    res = await session.execute(
        select(User).order_by(desc(User.points))
        .limit(20)
    )
    users = res.scalars().all()
    lines = ["👥 <b>Топ-20 участников</b>\n━━━━━━━━━━━━━━━━━━━\n"]
    for i, u in enumerate(users, 1):
        name = _escape_html(u.nickname or (f"@{u.username}" if u.username else str(u.telegram_id)))
        lines.append(f"{i}. {name} — {u.points} баллов")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="a:back")]])
    await cb.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)
    await cb.answer()


@router.message(Command("export"))
async def export_cmd(message: Message, session: AsyncSession) -> None:
    # /export excel
    if not await require_admin(session, message.from_user.id, message):
        return
    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) != 2 or parts[1].strip().lower() != "excel":
        await message.answer("Использование: /export excel")
        return
    await _do_export_excel(message, session)


@router.callback_query(F.data == "a:export_excel")
async def export_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await require_admin(session, cb.from_user.id, cb.message):
        await cb.answer()
        return
    await _do_export_excel(cb.message, session)
    await cb.answer()


async def _do_export_excel(message: Message, session: AsyncSession) -> None:
    await message.answer("📥 Готовлю файл Excel…")
    try:
        path = await export_to_excel(session)
        await message.answer_document(FSInputFile(path), caption="✅ Экспорт данных (.xlsx)")
        try:
            os.remove(path)
        except OSError:
            pass
    except Exception as e:
        logger.exception("Ошибка экспорта")
        await message.answer(f"Ошибка экспорта: {e}")


@router.callback_query(F.data == "a:logout")
async def logout_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    s = await get_admin_session(session, cb.from_user.id)
    s.is_logged_in = False
    await session.commit()
    await cb.message.answer("Вышел из админ-панели.")
    await cb.answer()


@router.callback_query(F.data == "a:judge")
async def judge_start(cb: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if not await require_admin(session, cb.from_user.id, cb.message):
        await cb.answer()
        return

    res = await session.execute(
        select(Submission)
        .where(Submission.status == SubmissionStatus.PENDING)
        .order_by(Submission.submission_date)
        .limit(1)
        .options(selectinload(Submission.user))
    )
    sub = res.scalar_one_or_none()
    if not sub:
        await cb.message.answer("Нет работ на оценке.")
        await cb.answer()
        return

    await state.clear()
    await state.update_data(submission_id=sub.id)
    author = sub.user.nickname or (f"@{sub.user.username}" if sub.user.username else str(sub.user.telegram_id))
    try:
        await cb.message.answer_photo(
            sub.photo_file_id,
            caption=(
                f"<b>Работа #{sub.id}</b>\n"
                f"<b>Автор:</b> {_escape_html(author)}\n"
                f"<b>Описание:</b> {_escape_html(sub.description or '—')}\n\n"
                "Оценка LAGS: выбери балл за <b>Visual Quality</b> (0–10)."
            ),
            parse_mode="HTML",
            reply_markup=score_kb("a:score_visual"),
        )
    except Exception as e:
        logger.warning("Не удалось отправить фото на оценку: %s", e)
        await cb.message.answer(
            f"Работа #{sub.id}\nАвтор: {author}\nОписание: {sub.description or '—'}\n\n"
            "Выбери Visual Quality (0–10):",
            reply_markup=score_kb("a:score_visual"),
        )

    await state.set_state(JudgeFSM.scoring_visual)
    await cb.answer()


@router.callback_query(F.data.startswith("a:score_visual:"), StateFilter(JudgeFSM.scoring_visual))
async def score_visual(cb: CallbackQuery, state: FSMContext) -> None:
    score = int(cb.data.split(":")[-1])
    await state.update_data(visual=score)
    await cb.message.answer("Creativity (0–10):", reply_markup=score_kb("a:score_creativity"))
    await state.set_state(JudgeFSM.scoring_creativity)
    await cb.answer()


@router.callback_query(F.data.startswith("a:score_creativity:"), StateFilter(JudgeFSM.scoring_creativity))
async def score_creativity(cb: CallbackQuery, state: FSMContext) -> None:
    score = int(cb.data.split(":")[-1])
    await state.update_data(creativity=score)
    await cb.message.answer("Technical Skills (0–10):", reply_markup=score_kb("a:score_technique"))
    await state.set_state(JudgeFSM.scoring_technique)
    await cb.answer()


@router.callback_query(F.data.startswith("a:score_technique:"), StateFilter(JudgeFSM.scoring_technique))
async def score_technique(cb: CallbackQuery, state: FSMContext) -> None:
    score = int(cb.data.split(":")[-1])
    await state.update_data(technique=score)
    await cb.message.answer("Overall Harmony (0–10):", reply_markup=score_kb("a:score_harmony"))
    await state.set_state(JudgeFSM.scoring_harmony)
    await cb.answer()


@router.callback_query(F.data.startswith("a:score_harmony:"), StateFilter(JudgeFSM.scoring_harmony))
async def score_harmony(cb: CallbackQuery, state: FSMContext) -> None:
    score = int(cb.data.split(":")[-1])
    await state.update_data(harmony=score)
    await cb.message.answer("Комментарий (можно «-» без комментария):")
    await state.set_state(JudgeFSM.waiting_comment)
    await cb.answer()


@router.message(JudgeFSM.waiting_comment)
async def judge_comment(message: Message, session: AsyncSession, state: FSMContext) -> None:
    comment = (message.text or "").strip()
    if len(comment) > 1000:
        await message.answer("Комментарий слишком длинный (до 1000 символов).")
        return
    await state.update_data(comment=None if comment in ("-", "") else comment)

    data = await state.get_data()
    total = int(data["visual"]) + int(data["creativity"]) + int(data["technique"]) + int(data["harmony"])
    await state.update_data(total=total)

    await message.answer(
        "<b>Проверка оценки</b>\n\n"
        f"Visual: {data['visual']}\n"
        f"Creativity: {data['creativity']}\n"
        f"Technique: {data['technique']}\n"
        f"Harmony: {data['harmony']}\n"
        f"<b>Итого:</b> {total}/40\n\n"
        "Выбери решение:",
        parse_mode="HTML",
        reply_markup=decision_kb(),
    )
    await state.set_state(JudgeFSM.waiting_decision)


@router.callback_query(F.data.startswith("a:decide:"), StateFilter(JudgeFSM.waiting_decision))
async def judge_decide(cb: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if not await require_admin(session, cb.from_user.id, cb.message):
        await state.clear()
        await cb.answer()
        return

    decision = cb.data.split(":")[-1]
    data = await state.get_data()
    submission_id = int(data["submission_id"])

    res = await session.execute(
        select(Submission)
        .where(Submission.id == submission_id)
        .options(selectinload(Submission.user))
    )
    sub = res.scalar_one_or_none()
    if not sub:
        await cb.message.answer("Работа не найдена.")
        await state.clear()
        await cb.answer()
        return

    admin = await get_user_by_tg(session, cb.from_user.id)
    if not admin:
        await cb.message.answer("Админ-пользователь не найден в базе. Повтори /admin_login.")
        await state.clear()
        await cb.answer()
        return

    # Записываем оценку как отдельную сущность (для истории)
    total = int(data["total"])
    evaluation = Evaluation(
        submission_id=sub.id,
        admin_id=admin.id,
        visual_quality=float(data["visual"]),
        creativity=float(data["creativity"]),
        technical_skills=float(data["technique"]),
        overall_harmony=float(data["harmony"]),
        total_score=float(total),
        comment=data.get("comment"),
        evaluation_date=datetime.utcnow(),
    )
    session.add(evaluation)

    # Обновляем submission (упрощённо: последняя оценка = итог)
    if decision == "accept":
        sub.visual_quality = float(data["visual"])
        sub.creativity = float(data["creativity"])
        sub.technical_skills = float(data["technique"])
        sub.overall_harmony = float(data["harmony"])
        sub.total_score = float(total)
        sub.level_achieved = calculate_level_from_score(float(total))
        sub.admin_comment = data.get("comment")
        sub.status = SubmissionStatus.EVALUATED

        sub.user.points += int(total)
        sub.user.level = recalc_user_level_by_points(sub.user.points)
    else:
        sub.admin_comment = data.get("comment")
        sub.status = SubmissionStatus.REJECTED

    await session.commit()

    # Уведомление участника
    try:
        if decision == "accept":
            msg = (
                f"✅ <b>Твоя работа #{sub.id} оценена!</b>\n\n"
                f"<b>Баллы:</b> {int(sub.total_score)}/40\n"
                f"<b>Комментарий:</b> {_escape_html(sub.admin_comment or '—')}"
            )
        else:
            msg = (
                f"❌ <b>Работа #{sub.id} отклонена</b>\n\n"
                f"<b>Комментарий:</b> {_escape_html(sub.admin_comment or '—')}"
            )
        await cb.message.bot.send_message(sub.user.telegram_id, msg, parse_mode="HTML")
    except Exception as e:
        logger.warning("Не удалось уведомить участника: %s", e)

    await cb.message.answer("Готово. Следующая работа — в меню «Оценить работы».")
    await state.clear()
    await cb.answer()

