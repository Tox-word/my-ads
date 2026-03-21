from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
import config

# --- ГЛАВНОЕ МЕНЮ ---
def main_menu():
    buttons = [
        # Рекламная кнопка (через WebApp)
        [InlineKeyboardButton(text="📺 Смотреть видео (0.5 ⭐)", web_app=WebAppInfo(url=config.ADSGRAM_URL))],
        
        # Основные функции
        [InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily_bonus")],
        [InlineKeyboardButton(text="📢 Задания на подписку", callback_data="tasks_list")],
        [InlineKeyboardButton(text="🔥 СПЕЦ-ЗАДАНИЯ", callback_data="high_reward")],

        [InlineKeyboardButton(text="🎫 Промокод", callback_data="promo_activate")],
        
        # Профиль и рефка в одну строку
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="👥 Рефералы", callback_data="refs")],
        
        # Сотрудничество
        [InlineKeyboardButton(text="🤝 Сотрудничество", url="https://t.me/tox6c9ty")] 
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- КНОПКИ В ПРОФИЛЕ ---
def profile_kb(can_withdraw: bool = False):
    buttons = []
    # Показываем кнопку вывода только если баланс позволяет (логика из main)
    if can_withdraw:
        buttons.append([InlineKeyboardButton(text="💳 Вывести ⭐", callback_data="withdraw_request")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ВЫБОР ВАЛЮТЫ ВЫВОДА ---
def withdraw_currency_kb():
    buttons = [
        [InlineKeyboardButton(text="💎 TON", callback_data="out_TON"),
         InlineKeyboardButton(text="💵 USDT", callback_data="out_USDT")],
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="out_STARS")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- КНОПКИ ДЛЯ ЗАДАНИЯ ---
def task_check_kb(url, task_id):
    buttons = [
        [InlineKeyboardButton(text="🔗 Перейти в канал", url=url)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data=f"check_task_{task_id}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="tasks_list")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- АДМИН-ПАНЕЛЬ ---
def admin_panel_kb():
    buttons = [
        [InlineKeyboardButton(text="📋 Список всех заданий", callback_data="adm_tasks_list")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
