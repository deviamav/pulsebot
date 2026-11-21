"""Reply keyboards for the main menu."""
from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from app.db.models import Role


# Button labels — used both for keyboards and text matching
BTN_NEW_TASK = "🆕 Создать задачу"
BTN_MY_TASKS_CUSTOMER = "📂 Мои задачи"
BTN_ACTIVE = "⚡ Активные"
BTN_FINISHED = "✅ Завершённые"

BTN_MY_TASKS_DESIGNER = "📂 Мои задачи"
BTN_NEW_TASKS = "🆕 Новые"
BTN_IN_PROGRESS = "🛠 В работе"

BTN_ALL_TASKS = "📋 Все задачи"
BTN_USERS = "👥 Пользователи"
BTN_STATS = "📊 Статистика"
BTN_ASSIGN_ROLE = "🎭 Назначить роль"
BTN_INVITES = "🎟 Инвайт-коды"

# Common buttons shown for all roles
BTN_PROFILE = "👤 Профиль"
BTN_HELP = "ℹ️ Помощь"
BTN_MENU = "🏠 Меню"

# Buttons for unauthenticated users
BTN_REDEEM_INVITE = "🎟 У меня есть инвайт-код"


# All known reply-keyboard labels.  Used by middlewares / focus handlers
# to tell "the user pressed a menu button" apart from "the user is
# typing free-form text" without having to import each constant by name.
ALL_MENU_BUTTONS: frozenset[str] = frozenset(
    {
        BTN_NEW_TASK,
        BTN_MY_TASKS_CUSTOMER,
        BTN_ACTIVE,
        BTN_FINISHED,
        BTN_MY_TASKS_DESIGNER,
        BTN_NEW_TASKS,
        BTN_IN_PROGRESS,
        BTN_ALL_TASKS,
        BTN_USERS,
        BTN_STATS,
        BTN_ASSIGN_ROLE,
        BTN_INVITES,
        BTN_PROFILE,
        BTN_HELP,
        BTN_MENU,
        BTN_REDEEM_INVITE,
    }
)


def main_menu(role: Role) -> ReplyKeyboardMarkup:
    """Return main menu keyboard tailored to user role."""
    if role == Role.CUSTOMER:
        rows = [
            [KeyboardButton(text=BTN_NEW_TASK)],
            [KeyboardButton(text=BTN_MY_TASKS_CUSTOMER)],
            [
                KeyboardButton(text=BTN_ACTIVE),
                KeyboardButton(text=BTN_FINISHED),
            ],
            [
                KeyboardButton(text=BTN_PROFILE),
                KeyboardButton(text=BTN_HELP),
            ],
        ]
    elif role == Role.DESIGNER:
        rows = [
            [KeyboardButton(text=BTN_MY_TASKS_DESIGNER)],
            [
                KeyboardButton(text=BTN_NEW_TASKS),
                KeyboardButton(text=BTN_IN_PROGRESS),
            ],
            [KeyboardButton(text=BTN_FINISHED)],
            [
                KeyboardButton(text=BTN_PROFILE),
                KeyboardButton(text=BTN_HELP),
            ],
        ]
    else:
        rows = [
            [KeyboardButton(text=BTN_ALL_TASKS)],
            [
                KeyboardButton(text=BTN_USERS),
                KeyboardButton(text=BTN_STATS),
            ],
            [
                KeyboardButton(text=BTN_INVITES),
                KeyboardButton(text=BTN_ASSIGN_ROLE),
            ],
            [
                KeyboardButton(text=BTN_PROFILE),
                KeyboardButton(text=BTN_HELP),
            ],
        ]
    return ReplyKeyboardMarkup(
        keyboard=rows, resize_keyboard=True, is_persistent=True
    )


def guest_menu() -> ReplyKeyboardMarkup:
    """Menu shown to unauthenticated users (only invite-code button)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_REDEEM_INVITE)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def remove_menu() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
