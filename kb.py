from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
import config

# Главное меню
def main_menu():
    buttons = [
        # Кнопка для рекламы через GitHub/Vercel
        [InlineKeyboardButton(text="📺 Смотреть видео (0.5 ⭐)", web_app=WebAppInfo(url=config.ADSGRAM_URL))],
        [InlineKeyboardButton(text="📢 Задания на подписку", callback_data="tasks_list")],
        [InlineKeyboardButton(text="🔥 СПЕЦ-ЗАДАНИЯ (ОТ 50 ⭐)", callback_data="high_reward")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="👥 Рефералы", callback_data="refs")],
        # Ссылка на твою личку для сотрудничества — это самый простой и надежный способ
        [InlineKeyboardButton(text="🤝 Сотрудничество", url="https://t.me/tox6c9ty")] 
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Меню выбора валюты вывода
def withdraw_currency_kb():
    buttons = [
        [InlineKeyboardButton(text="Крипто (TON)", callback_data="out_TON")],
        [InlineKeyboardButton(text="Крипто (USDT)", callback_data="out_USDT")],
        [InlineKeyboardButton(text="Telegram Stars", callback_data="out_STARS")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Кнопка для конкретного задания
def task_button(url, task_id):
    buttons = [
        [InlineKeyboardButton(text="🔗 Перейти в канал", url=url)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data=f"check_{task_id}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="tasks_list")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Кнопка админ-панели (для сообщения /admin)
def admin_panel_kb():
    buttons = [
        [InlineKeyboardButton(text="📋 Список всех заданий", callback_data="adm_tasks_list")],
        [InlineKeyboardButton(text="📢 Рассылка (в разработке)", callback_data="adm_broadcast")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
