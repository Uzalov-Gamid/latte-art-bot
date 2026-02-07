"""
Роутер участника:
- регистрация (/start)
- меню (/menu)
- профиль (/profile)
- отправка работы (/submit) с лимитом
- рейтинг (/leaderboard), лучшие работы (/best_works), челленджи (/challenges)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Submission, SubmissionStatus, User
from utils import check_submission_limit, get_user_ranking

logger = logging.getLogger(__name__)

router = Router()


class RegistrationFSM(StatesGroup):
    waiting_nickname = State()


class SubmitFSM(StatesGroup):
    waiting_photo = State()
    waiting_description = State()
    confirming = State()


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


def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Профиль", callback_data="u:profile"),
                InlineKeyboardButton(text="📸 Подать работу", callback_data="u:submit"),
            ],
            [
                InlineKeyboardButton(text="🏆 Рейтинг", callback_data="u:leaderboard"),
                InlineKeyboardButton(text="⭐ Лучшие работы", callback_data="u:best_works"),
            ],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="u:help")],
        ]
    )


def confirm_submit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="u:submit_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="u:submit_cancel"),
            ]
        ]
    )


async def get_user_by_tg(session: AsyncSession, telegram_id: int) -> Optional[User]:
    res = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return res.scalar_one_or_none()


@router.message(Command("start"))
async def start_cmd(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if user:
        await message.answer(
            f"✨ <b>Рад снова видеть, {_escape_html(user.nickname)}!</b> ☕️\n\n"
            "Выбери действие в меню ниже 👇",
            reply_markup=menu_kb(),
            parse_mode="HTML",
        )
        return

    await state.clear()
    await message.answer(
        "☕️ <b>Добро пожаловать в Latte Art Competition!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Здесь ты можешь:\n"
        "• Подавать работы по латте-арту\n"
        "• Получать оценку по системе LAGS\n"
        "• Соревноваться с другими участниками\n\n"
        "Введи своё имя",
        parse_mode="HTML",
    )
    await state.set_state(RegistrationFSM.waiting_nickname)


@router.message(StateFilter(RegistrationFSM.waiting_nickname))
async def reg_nickname(message: Message, session: AsyncSession, state: FSMContext) -> None:
    nickname = (message.text or "").strip()
    if not nickname or len(nickname) > 30:
        await message.answer("Ник/имя должно быть непустым и до 30 символов. Попробуй ещё раз.")
        return

    await state.update_data(nickname=nickname)
    await _finish_registration(message, session, state, nickname=nickname)


async def _finish_registration(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    nickname: str,
) -> None:
    user = User(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        nickname=nickname,
        city=None,
        points=0,
        submissions_count=0,
        is_admin=False,
        is_banned=False,
        last_activity=datetime.utcnow(),
    )
    session.add(user)
    await session.commit()
    await state.clear()

    await message.answer(
        "🎉 <b>Регистрация завершена!</b>\n\n"
        f"👤 <b>Имя:</b> {_escape_html(nickname)}\n\n"
        "Теперь ты можешь участвовать в соревнованиях!",
        reply_markup=menu_kb(),
        parse_mode="HTML",
    )


@router.message(Command("menu"))
async def menu_cmd(message: Message, session: AsyncSession) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("📌 Сначала зарегистрируйся: /start")
        return
    await message.answer(
        "📋 <b>Главное меню</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nВыбери действие:",
        reply_markup=menu_kb(),
        parse_mode="HTML",
    )


@router.message(Command("profile"))
async def profile_cmd(message: Message, session: AsyncSession) -> None:
    await _send_profile(message, session, telegram_id=message.from_user.id)


@router.callback_query(F.data == "u:profile")
async def profile_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    await _send_profile(cb.message, session, telegram_id=cb.from_user.id)
    await cb.answer()


async def _send_profile(message: Message, session: AsyncSession, telegram_id: int) -> None:
    user = await get_user_by_tg(session, telegram_id)
    if not user:
        await message.answer("📌 Сначала зарегистрируйся: /start")
        return

    rank = await get_user_ranking(session, user.id)

    res = await session.execute(
        select(Submission)
        .where(Submission.user_id == user.id)
        .order_by(desc(Submission.submission_date))
        .limit(5)
    )
    last_subs = res.scalars().all()

    lines = [
        "👤 <b>Твой профиль</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"👤 <b>Имя:</b> {_escape_html(user.nickname)}",
        f"⭐ <b>Баллы:</b> {user.points}",
        f"📊 <b>Место в рейтинге:</b> #{rank}",
        f"📸 <b>Работ отправлено:</b> {user.submissions_count}",
        "",
        "📸 <b>Последние работы:</b>",
    ]
    if not last_subs:
        lines.append("— пока нет работ")
    else:
        for s in last_subs:
            lines.append(
                f"— #{s.id} • {s.status.value} • {s.total_score:.0f}/40 • "
                f"{s.submission_date.strftime('%d.%m.%Y')}"
            )

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=menu_kb())


@router.message(Command("submit"))
async def submit_cmd(message: Message, session: AsyncSession, state: FSMContext, telegram_id: Optional[int] = None) -> None:
    tg_id = telegram_id if telegram_id is not None else (message.from_user.id if message.from_user else None)
    if not tg_id:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    user = await get_user_by_tg(session, tg_id)
    if not user:
        await message.answer("📌 Сначала зарегистрируйся: /start")
        return
    can_submit, count = await check_submission_limit(session, user.id, weeks=1)
    if not can_submit:
        await message.answer(
            f"Лимит: 3 работы в неделю. Сейчас у тебя уже {count} за последние 7 дней."
        )
        return

    await state.clear()
    await message.answer(
        "📸 <b>Подача работы</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Отправь <b>фотографию</b> своей работы по латте-арту.\n\n"
        "💡 Пришли именно изображение (не документ).",
        parse_mode="HTML",
    )
    await state.set_state(SubmitFSM.waiting_photo)


@router.callback_query(F.data == "u:submit")
async def submit_cb(cb: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await cb.answer()
    await submit_cmd(cb.message, session, state, telegram_id=cb.from_user.id)


@router.message(StateFilter(SubmitFSM.waiting_photo), F.photo)
async def submit_photo(message: Message, state: FSMContext) -> None:
    file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=file_id)
    await message.answer(
        "📝 <b>Опиши работу</b> (до 300 символов):\n\n"
        "Например:\n"
        "• Паттерн — сердце, тюльпан, розетта\n"
        "• Технику — free pour, etching\n"
        "• Краткий комментарий"
    )
    await state.set_state(SubmitFSM.waiting_description)


@router.message(StateFilter(SubmitFSM.waiting_photo))
async def submit_photo_invalid(message: Message) -> None:
    await message.answer("Нужна фотография (изображение). Пришли фото одним сообщением.")


@router.message(StateFilter(SubmitFSM.waiting_description))
async def submit_description(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Описание не должно быть пустым. Напиши пару слов (до 300 символов).")
        return
    if len(text) > 300:
        await message.answer("Слишком длинно (до 300 символов). Сократи и отправь ещё раз.")
        return

    await state.update_data(description=text)
    data = await state.get_data()

    await message.answer_photo(
        data["photo_file_id"],
        caption=(
            "✅ <b>Проверь перед отправкой</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 <b>Описание:</b> {_escape_html(text)}\n\n"
            "Всё верно? Нажми «Отправить» 👇"
        ),
        parse_mode="HTML",
        reply_markup=confirm_submit_kb(),
    )
    await state.set_state(SubmitFSM.confirming)


@router.callback_query(F.data == "u:submit_cancel", StateFilter(SubmitFSM.confirming))
async def submit_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.answer("Ок, отменил отправку.", reply_markup=menu_kb())
    await cb.answer()


@router.callback_query(F.data == "u:submit_confirm", StateFilter(SubmitFSM.confirming))
async def submit_confirm(cb: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    user = await get_user_by_tg(session, cb.from_user.id)
    if not user:
        await cb.message.answer("📌 Сначала зарегистрируйся: /start")
        await state.clear()
        await cb.answer()
        return

    can_submit, count = await check_submission_limit(session, user.id, weeks=1)
    if not can_submit:
        await cb.message.answer(
            f"Лимит: 3 работы в неделю. Сейчас у тебя уже {count} за последние 7 дней."
        )
        await state.clear()
        await cb.answer()
        return

    data = await state.get_data()
    submission = Submission(
        user_id=user.id,
        photo_file_id=data["photo_file_id"],
        description=data["description"],
        status=SubmissionStatus.PENDING,
    )
    session.add(submission)
    user.submissions_count += 1
    user.last_activity = datetime.utcnow()
    await session.commit()
    await state.clear()

    await cb.message.answer(
        "🎉 <b>Работа отправлена на оценку!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 ID работы: <b>#{submission.id}</b>\n\n"
        "Администратор оценит её по системе LAGS в ближайшее время.\n"
        "Ты получишь уведомление с результатом! ✉️",
        reply_markup=menu_kb(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(Command("leaderboard"))
async def leaderboard_cmd(message: Message, session: AsyncSession) -> None:
    res = await session.execute(
        select(User).order_by(desc(User.points))
        .limit(50)
    )
    users = res.scalars().all()
    if not users:
        await message.answer(
            "📊 <b>Рейтинг пока пуст</b>\n\n"
            "Стань первым — подай работу! 📸"
        )
        return

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["🏆 <b>Топ-50 рейтинга</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, u in enumerate(users, start=1):
        medal = medals.get(i, f"{i}.")
        display = u.nickname or (f"@{u.username}" if u.username else str(u.telegram_id))
        lines.append(f"{medal} {_escape_html(display)} — <b>{u.points}</b> баллов")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=menu_kb())


@router.callback_query(F.data == "u:leaderboard")
async def leaderboard_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    await leaderboard_cmd(cb.message, session)
    await cb.answer()


@router.message(Command("best_works"))
async def best_works_cmd(message: Message, session: AsyncSession) -> None:
    res = await session.execute(
        select(Submission)
        .where(Submission.status == SubmissionStatus.EVALUATED)
        .order_by(desc(Submission.total_score))
        .limit(5)
        .options(selectinload(Submission.user))
    )
    subs = res.scalars().all()
    if not subs:
        await message.answer(
            "📸 <b>Пока нет оценённых работ</b>\n\n"
            "Будь первым! Подай работу и жди результат."
        )
        return

    await message.answer(
        "⭐ <b>Топ-5 лучших работ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML",
        reply_markup=menu_kb(),
    )
    for s in subs:
        author = s.user.nickname or (f"@{s.user.username}" if s.user.username else str(s.user.telegram_id))
        caption = (
            f"👤 <b>Автор:</b> {_escape_html(author)}\n"
            f"🏅 <b>Баллы:</b> {int(s.total_score)}/40\n"
            f"📋 <b>Комментарий:</b> {_escape_html(s.admin_comment or '—')}"
        )
        try:
            await message.answer_photo(s.photo_file_id, caption=caption, parse_mode="HTML")
        except Exception as e:
            logger.warning("Не удалось отправить фото лучшей работы: %s", e)


@router.callback_query(F.data == "u:best_works")
async def best_works_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    await best_works_cmd(cb.message, session)
    await cb.answer()


@router.callback_query(F.data == "u:help")
async def help_cb(cb: CallbackQuery) -> None:
    await cb.message.answer(
        "❓ <b>Помощь</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 <b>Команды:</b>\n"
        "/start — регистрация\n"
        "/menu — главное меню\n"
        "/profile — мой профиль\n"
        "/submit — подать работу\n"
        "/leaderboard — рейтинг\n"
        "/best_works — лучшие работы\n\n"
        "📋 <b>Правила проведения соревнования</b>\n\n"
        "<b>Подача работ:</b>\n"
        "• Не более <b>3 работ в неделю</b> (7 дней)\n"
        "• Каждая работа — фото латте-арта + краткое описание (до 300 символов)\n"
        "• Присылай именно фото (не документ)\n\n"
        "<b>Оценка:</b>\n"
        "Работы оцениваются по системе LAGS по 4 критериям:\n"
        "• <b>Visual Quality</b> — визуальное качество (0–10)\n"
        "• <b>Creativity</b> — креативность (0–10)\n"
        "• <b>Technical Skills</b> — техника (0–10)\n"
        "• <b>Overall Harmony</b> — общая гармония (0–10)\n"
        "Максимум: <b>40 баллов</b> за работу.\n\n"
        "Баллы за принятые работы суммируются. Побеждает тот, у кого больше очков!\n\n"
        "Результат оценки придёт тебе в личные сообщения.",
        parse_mode="HTML",
        reply_markup=menu_kb(),
    )
    await cb.answer()

