import asyncio
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import config as cfg
import database as db
import kb

from flask import Flask
from threading import Thread

# --- ТЕХНИЧЕСКИЙ БЛОК (Keep Alive для Render) ---
app = Flask('')

@app.route('/')
def home():
    return "Money Farm is online!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# --- СОСТОЯНИЯ (Для админки и будущих функций) ---
class AdminStates(StatesGroup):
    wait_broadcast_text = State()  # Ожидание текста для рассылки

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=cfg.BOT_TOKEN)
# Используем хранилище в памяти для состояний
dp = Dispatcher(storage=MemoryStorage())

# --- ГЛОБАЛЬНЫЕ ПРОВЕРКИ ---

async def check_main_subs(user_id: int):
    """Проверка подписки на каналы из config.py"""
    if user_id == cfg.ADMIN_ID:
        return True
    for channel in cfg.REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True

async def is_bad_user(message: types.Message):
    """Проверка на фрод: аватарка и юзернейм"""
    try:
        photos = await bot.get_user_profile_photos(message.from_user.id)
        if photos.total_count == 0:
            return "❌ Ошибка: У вас нет фото профиля. Добавьте его для работы с ботом."
        
        if not message.from_user.username:
            return "❌ Ошибка: У вас не установлен @username."
    except Exception:
        return "⚠️ Ошибка при проверке аккаунта."
    return None

# --- ОБРАБОТЧИК /START ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    
    # 1. Проверка на "живого" пользователя (Аватарка + Ник)
    bad_msg = await is_bad_user(message)
    if bad_msg:
        return await message.answer(bad_msg)
    
    # 2. Проверка: есть ли юзер в базе?
    existing_user = db.get_user(user_id)
    
    # 3. Логика реферальной ссылки (работает только для НОВЫХ)
    ref_id = None
    if not existing_user and command.args and command.args.isdigit():
        if int(command.args) != user_id:
            ref_id = int(command.args)
            
    # Регистрируем в базе (add_user должна возвращать True, если юзер новый)
    is_new = db.add_user(user_id, ref_id)
    
    # 4. Проверка обязательной подписки (ОП)
    if not await check_main_subs(user_id):
        channels_str = "\n".join(cfg.REQUIRED_CHANNELS)
        return await message.answer(
            f"❌ **Доступ ограничен!**\n\nДля работы с ботом подпишитесь на каналы:\n{channels_str}\n\n"
            f"После подписки нажмите /start снова.",
            parse_mode="Markdown"
        )

    # 5. Начисление бонусов за вход (L1 и L2)
    # Срабатывает только если юзер НОВЫЙ и только что прошел проверку подписки
    if is_new:
        if ref_id:
            # Начисляем Папе (L1) - 5.0 звезд
            db.update_balance(ref_id, 5.0)
            
            # Ищем Дедушку (L2) через данные Папы
            parent_data = db.get_user(ref_id)
            if parent_data and parent_data['ref_id']:
                # Начисляем Дедушке (L2) - 1.0 звезда
                db.update_balance(parent_data['ref_id'], 1.0)
            
            # Уведомляем пригласителя
            try:
                await bot.send_message(ref_id, "👥 **У вас новый активный реферал!**\n💰 Бонус: +5.0 ⭐")
            except:
                pass

    # 6. Отправка главного меню
    await message.answer(
        "🏝 **Добро пожаловать на Money Farm!**\n\nНачинайте выполнять задания и приглашать друзей, чтобы зарабатывать звёзды.",
        reply_markup=kb.main_menu(),
        parse_mode="Markdown"
    )

# --- ПАНЕЛЬ УПРАВЛЕНИЯ (ТОЛЬКО ДЛЯ ТЕБЯ) ---
@dp.message(Command("admin"), F.from_user.id == cfg.ADMIN_ID)
async def admin_panel(message: types.Message):
    # Получаем общую статистику из базы (нужны функции в database.py)
    stats = db.get_admin_stats() 
    
    text = (
        f"🖥 **АДМИН-ПАНЕЛЬ MONEY FARM**\n\n"
        f"👥 Всего пользователей: `{stats['users_count']}`\n"
        f"💰 Звезд в системе: `{round(stats['total_balance'], 2)}` ⭐\n"
        f"📢 Активных заданий: `{stats['tasks_count']}`\n"
    )
    
    # Кнопки для управления (настраиваются в kb.py)
    await message.answer(text, reply_markup=kb.admin_panel_kb(), parse_mode="Markdown")

# --- РУЧНОЕ УПРАВЛЕНИЕ БАЛАНСОМ ---
# Формат: /give 1234567 100 (или -100 для списания)
@dp.message(Command("give"), F.from_user.id == cfg.ADMIN_ID)
async def admin_give_stars(message: types.Message, command: CommandObject):
    try:
        args = command.args.split()
        target_id = int(args[0])
        amount = float(args[1])
        
        db.update_balance(target_id, amount)
        
        await message.answer(f"✅ Баланс пользователя `{target_id}` изменен на {amount} ⭐")
        
        # Пробуем уведомить пользователя о бонусе
        if amount > 0:
            try:
                await bot.send_message(target_id, f"🎁 **Администратор начислил вам бонус:** +{amount} ⭐!")
            except: pass
    except:
        await message.answer("❌ Ошибка! Формат: `/give ID СУММА`")

# --- МАССОВАЯ РАССЫЛКА ---
# Формат: /send Текст сообщения
@dp.message(Command("send"), F.from_user.id == cfg.ADMIN_ID)
async def admin_broadcast(message: types.Message, command: CommandObject):
    broadcast_text = command.args
    if not broadcast_text:
        return await message.answer("❌ Введите текст: `/send Всем привет!`")
    
    # Получаем список всех ID из базы
    users = db.get_all_users()
    count = 0
    await message.answer(f"🚀 Начинаю рассылку на {len(users)} чел...")
    
    for user in users:
        try:
            # user[0] - это ID пользователя в списке кортежей
            await bot.send_message(user[0], broadcast_text)
            count += 1
            # Микро-пауза, чтобы Telegram не забанил за спам
            await asyncio.sleep(0.05) 
        except:
            continue
            
    await message.answer(f"✅ Рассылка завершена!\n📩 Доставлено: {count} пользователям.")

# --- КНОПКА: ПРОФИЛЬ ---
@dp.callback_query(F.data == "profile")
async def cb_profile(call: types.CallbackQuery):
    # Обновляем данные из базы
    user = db.get_user(call.from_user.id)
    if not user: return
    
    # Расчет курса (если нужно показать в $)
    balance = user['balance']
    usd_val = round(balance * 0.015, 2)
    
    text = (
        f"👤 **ВАШ ПРОФИЛЬ**\n\n"
        f"💰 Баланс: `{balance}` ⭐\n"
        f"💵 В долларах: `${usd_val}`\n"
        f"🆔 Ваш ID: `{call.from_user.id}`"
    )
    
    await call.message.edit_text(text, reply_markup=kb.main_menu(), parse_mode="Markdown")

# --- ЛОГИКА ЗАДАНИЙ ---

# 1. Показ списка доступных заданий
@dp.callback_query(F.data == "tasks_list")
async def cb_tasks_list(call: types.CallbackQuery):
    tasks = db.get_active_tasks() # Функция должна возвращать список заданий из базы
    
    if not tasks:
        return await call.answer("📭 Пока нет доступных заданий!", show_alert=True)
        
    keyboard = []
    for t in tasks:
        # Проверяем, не выполнял ли юзер это задание ранее
        if not db.is_task_completed(call.from_user.id, t['id']):
            keyboard.append([types.InlineKeyboardButton(
                text=f"🎯 {t['title']} ({t['reward']} ⭐)", 
                callback_data=f"view_task_{t['id']}"
            )])
    
    keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")])
    
    await call.message.edit_text(
        "🎯 **Доступные задания:**\nПодпишитесь на каналы партнеров и получите награду!",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown"
    )

# 2. Просмотр конкретного задания
@dp.callback_query(F.data.startswith("view_task_"))
async def cb_view_task(call: types.CallbackQuery):
    task_id = int(call.data.split("_")[2])
    task = db.get_task_by_id(task_id)
    
    if not task:
        return await call.answer("❌ Задание не найдено.")

    text = (
        f"📢 **Задание:** {task['title']}\n"
        f"💰 **Награда:** {task['reward']} ⭐\n\n"
        f"Чтобы получить награду, подпишитесь на канал по ссылке ниже и нажмите кнопку проверки."
    )
    
    await call.message.edit_text(
        text, 
        reply_markup=kb.task_check_kb(task['url'], task['id']), # Кнопка-ссылка + кнопка "Проверить"
        parse_mode="Markdown"
    )

# 3. Кнопка "Проверить" подписку
@dp.callback_query(F.data.startswith("check_task_"))
async def cb_check_task(call: types.CallbackQuery):
    task_id = int(call.data.split("_")[2])
    task = db.get_task_by_id(task_id)
    user_id = call.from_user.id
    
    try:
        # Пытаемся проверить статус юзера в канале задания (task['chat_id'] - например, @mychannel)
        member = await bot.get_chat_member(chat_id=task['chat_id'], user_id=user_id)
        
        if member.status in ["member", "administrator", "creator"]:
            # Начисляем награду в базе
            success = db.complete_user_task(user_id, task_id, task['reward'])
            if success:
                await call.answer("✅ Награда начислена!", show_alert=True)
                await cb_tasks_list(call) # Возвращаем к списку
            else:
                await call.answer("❌ Вы уже получили награду за это задание.")
        else:
            await call.answer("❌ Вы не подписались на канал!", show_alert=True)
            
    except Exception:
        await call.answer("⚠️ Ошибка проверки. Убедитесь, что бот является админом в целевом канале.", show_alert=True)

# --- ГЛАВНЫЙ ЗАПУСК ---

async def main():
    # 1. Инициализируем таблицы в базе (если их нет)
    db.init_db()
    
    # 2. Запускаем фоновый веб-сервер (Flask) для Render
    keep_alive()
    
    print("🚀 Money Farm Bot успешно запущен!")
    
    # 3. Чистим очередь обновлений и запускаем опрос
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
