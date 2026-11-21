"""Common handlers: /start, /help, /cancel, profile, invite redemption."""
from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import guest_menu, main_menu
from app.bot.keyboards.reply import (
    BTN_HELP,
    BTN_MENU,
    BTN_PROFILE,
    BTN_REDEEM_INVITE,
)
from app.bot.states import InviteRedeemStates
from app.db.models import Role, User
from app.services import InviteService
from app.services.invite import InviteServiceError
from app.utils.datetime import format_dt

router = Router(name="common")
# Fallback router is intentionally separate and MUST be included LAST in the
# main router, otherwise its catch-all ``@router.message()`` handler would
# eat every message before role-specific routers (admin/customer/designer)
# have a chance to match their reply-keyboard buttons.
fallback_router = Router(name="common.fallback")


WELCOME_BY_ROLE: dict[Role, str] = {
    Role.ADMIN: (
        "<b>Здравствуйте, администратор.</b>\n\n"
        "Вы можете управлять пользователями, выдавать инвайт-коды, "
        "просматривать все задачи и статистику."
    ),
    Role.CUSTOMER: (
        "<b>Добро пожаловать в систему задач.</b>\n\n"
        "Создавайте задачи, прикрепляйте файлы и получайте результаты "
        "от дизайнеров. Вся коммуникация — анонимная и идёт через бота."
    ),
    Role.DESIGNER: (
        "<b>Добро пожаловать, дизайнер.</b>\n\n"
        "Здесь вы увидите назначенные на вас задачи, сможете менять "
        "статусы, добавлять комментарии и отправлять результаты."
    ),
}


HELP_BY_ROLE: dict[Role, str] = {
    Role.CUSTOMER: (
        "<b>Как пользоваться ботом</b>\n\n"
        "• <b>🆕 Создать задачу</b> — описать задачу и выбрать исполнителя\n"
        "• <b>📂 Мои задачи</b> — все ваши задачи\n"
        "• <b>⚡ Активные / ✅ Завершённые</b> — фильтр по состоянию\n"
        "• <b>👤 Профиль</b> — информация о вашем аккаунте\n\n"
        "В карточке задачи вы можете комментировать, добавлять файлы, "
        "принимать выполнение или возвращать на доработку."
    ),
    Role.DESIGNER: (
        "<b>Как пользоваться ботом</b>\n\n"
        "• <b>📂 Мои задачи</b> — все задачи, назначенные на вас\n"
        "• <b>🆕 Новые</b> — задачи в статусе «Новая»\n"
        "• <b>🛠 В работе</b> — «В работе» / «На проверке» / «Нужны правки»\n"
        "• <b>✅ Завершённые</b> — «Выполнена» / «Закрыта»\n\n"
        "В карточке задачи меняйте статус, отправляйте файлы-результаты "
        "и комментарии. Заказчик увидит их через бота анонимно."
    ),
    Role.ADMIN: (
        "<b>Как пользоваться ботом (админ)</b>\n\n"
        "• <b>📋 Все задачи</b>, <b>👥 Пользователи</b>, <b>📊 Статистика</b>\n"
        "• <b>🎟 Инвайт-коды</b> — создать инвайт для нового пользователя\n"
        "• <b>🎭 Назначить роль</b> — изменить роль существующего пользователя\n\n"
        "Команды для блокировки: <code>/ban &lt;user_id&gt;</code>, "
        "<code>/unban &lt;user_id&gt;</code>."
    ),
}


def _help_text(user: User | None) -> str:
    if user is None:
        return (
            "<b>Этот бот доступен только приглашённым пользователям.</b>\n\n"
            "Чтобы войти, попросите администратора выдать вам инвайт-код "
            "или откройте ссылку-приглашение.\n\n"
            "Если у вас уже есть код — нажмите кнопку "
            f"<b>{BTN_REDEEM_INVITE}</b>."
        )
    return HELP_BY_ROLE.get(user.role, "Справка недоступна.")


# ---------- /start ----------


@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(
    message: Message,
    command: CommandObject,
    user: User | None,
    state: FSMContext,
    invite_service: InviteService,
) -> None:
    """Handle deep-link of form ``/start <invite_code>``."""
    await state.clear()
    code = (command.args or "").strip()

    if user is not None and user.is_active:
        await message.answer(
            "Вы уже зарегистрированы — инвайт-код не нужен.",
            reply_markup=main_menu(user.role),
        )
        return

    try:
        invite = await invite_service.validate(code)
    except InviteServiceError as exc:
        await message.answer(
            f"❌ {exc}\n\nОбратитесь к администратору за новым кодом.",
            reply_markup=guest_menu(),
        )
        return

    await state.set_state(InviteRedeemStates.waiting_name)
    await state.update_data(invite_code=invite.code)
    await message.answer(
        f"✅ Инвайт-код принят. Роль: <b>{invite.role.label}</b>.\n\n"
        "Введите, пожалуйста, ваше имя и фамилию (2–100 символов) — "
        "именно их увидят другие участники."
    )


@router.message(CommandStart())
async def cmd_start(message: Message, user: User | None, state: FSMContext) -> None:
    """Default ``/start`` without deep link."""
    await state.clear()
    if user is None or not user.is_active:
        await message.answer(
            "<b>Доступ ограничен.</b>\n\n"
            "Этот бот — для внутренней команды. Чтобы войти, получите "
            "инвайт-код у администратора.\n\n"
            "Если у вас уже есть код — нажмите кнопку ниже.",
            reply_markup=guest_menu(),
        )
        return

    await message.answer(
        WELCOME_BY_ROLE.get(user.role, "Добро пожаловать."),
        reply_markup=main_menu(user.role),
    )


# ---------- /help ----------


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def cmd_help(message: Message, user: User | None) -> None:
    reply = main_menu(user.role) if user and user.is_active else guest_menu()
    await message.answer(_help_text(user), reply_markup=reply)


# ---------- /cancel ----------


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message, state: FSMContext, user: User | None
) -> None:
    await state.clear()
    reply = (
        main_menu(user.role) if user and user.is_active else guest_menu()
    )
    await message.answer("Действие отменено.", reply_markup=reply)


# ---------- Menu button ----------


@router.message(F.text == BTN_MENU)
async def cmd_menu(message: Message, user: User | None) -> None:
    if user is None or not user.is_active:
        await message.answer("Доступ ограничен.", reply_markup=guest_menu())
        return
    await message.answer("Главное меню:", reply_markup=main_menu(user.role))


# ---------- Profile ----------


@router.message(F.text == BTN_PROFILE)
async def cmd_profile(message: Message, user: User | None) -> None:
    if user is None or not user.is_active:
        await message.answer("Доступ ограничен.", reply_markup=guest_menu())
        return

    text = (
        "<b>Ваш профиль</b>\n\n"
        f"<b>Имя:</b> {escape(user.full_name)}\n"
        f"<b>Роль:</b> {user.role.label}\n"
        f"<b>Зарегистрирован:</b> {format_dt(user.created_at)}\n"
        f"<b>ID в системе:</b> #{user.id}"
    )
    await message.answer(text, reply_markup=main_menu(user.role))


# ---------- Invite redemption flow ----------


@router.message(F.text == BTN_REDEEM_INVITE)
async def redeem_start(
    message: Message, state: FSMContext, user: User | None
) -> None:
    if user is not None and user.is_active:
        await message.answer(
            "Вы уже зарегистрированы.", reply_markup=main_menu(user.role)
        )
        return
    await state.set_state(InviteRedeemStates.waiting_code)
    await message.answer(
        "Пришлите, пожалуйста, ваш инвайт-код одним сообщением."
    )


@router.message(InviteRedeemStates.waiting_code, F.text)
async def redeem_receive_code(
    message: Message,
    state: FSMContext,
    invite_service: InviteService,
) -> None:
    try:
        invite = await invite_service.validate(message.text or "")
    except InviteServiceError as exc:
        await message.answer(
            f"❌ {exc}\n\nПопробуйте ещё раз или /cancel.",
        )
        return

    await state.set_state(InviteRedeemStates.waiting_name)
    await state.update_data(invite_code=invite.code)
    await message.answer(
        f"✅ Код принят. Роль: <b>{invite.role.label}</b>.\n\n"
        "Введите ваше имя и фамилию (2–100 символов)."
    )


@router.message(InviteRedeemStates.waiting_name, F.text)
async def redeem_receive_name(
    message: Message,
    state: FSMContext,
    invite_service: InviteService,
    bot: Bot,
) -> None:
    if message.from_user is None:
        return

    name = (message.text or "").strip()
    if not (2 <= len(name) <= 100):
        await message.answer("Имя должно быть от 2 до 100 символов.")
        return

    data = await state.get_data()
    code = str(data.get("invite_code", ""))

    try:
        user = await invite_service.redeem(
            code=code, telegram_id=message.from_user.id, full_name=name
        )
    except InviteServiceError as exc:
        await message.answer(f"❌ {exc}")
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"🎉 Добро пожаловать, <b>{escape(user.full_name)}</b>!\n\n"
        + WELCOME_BY_ROLE.get(user.role, ""),
        reply_markup=main_menu(user.role),
    )


# ---------- No-op + fallback ----------


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery) -> None:
    await cb.answer()


@fallback_router.message()
async def fallback(message: Message, user: User | None) -> None:
    if user is None or not user.is_active:
        await message.answer(
            "Этот бот — для внутренней команды. Нажмите "
            f"<b>{BTN_REDEEM_INVITE}</b>, если у вас есть инвайт.",
            reply_markup=guest_menu(),
        )
        return
    await message.answer(
        "Не понял команду. Воспользуйтесь меню или кнопкой «Помощь».",
        reply_markup=main_menu(user.role),
    )
