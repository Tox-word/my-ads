import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime, timedelta

import config
import database as db
import kb

from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Money Farm is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ (ПРОВЕРКА ПОДПИСКИ) ---
async def check_main_subs(user_id: int):
    # Если ты админ, тебе проверку проходить не нужно
    if user_id == config.ADMIN_ID:
        return True
    for channel in config.REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True

# --- ПРОВЕРКА АККАУНТА (АНТИ-ФРОД) ---
async def is_bad_user(message: types.Message):
    # Проверка на наличие фото профиля
    photos = await bot.get_user_profile_photos(message.from_user.id)
    if photos.total_count == 0:
        return "❌ Ошибка: У вас нет фото профиля. Бот работает только с реальными аккаунтами."
    # Проверка на юзернейм
    if not message.from_user.username:
        return "❌ Ошибка: У вас не установлен @username в настройках Telegram."
    return None


# --- АДМИН-КОМАНДЫ ---

# Добавление задания с временем жизни
@dp.message(F.text.startswith("/add"), F.from_user.id == config.ADMIN_ID)
async def admin_add_task(message: types.Message):
    try:
        # Формат: /add Название Ссылка Награда @юзернейм Часы
        parts = message.text.split(" ")
        title, url, reward, chat_id, hours = parts[1], parts[2], float(parts[3]), parts[4], int(parts[5])
        
        expire_time = datetime.now() + timedelta(hours=hours)
        db.add_task(title, url, reward, chat_id, expire_time) 
        
        await message.answer(f"✅ Задание '{title}' добавлено на {hours} ч.!")
    except:
        await message.answer("❌ Ошибка! Формат: `/add Название Ссылка Награда @юзернейм ЧАСЫ`", parse_mode="Markdown")

# Удаление задания по ID
@dp.message(F.text.startswith("/del"), F.from_user.id == config.ADMIN_ID)
async def admin_del_task(message: types.Message):
    try:
        task_id = int(message.text.split(" ")[1])
        db.delete_task(task_id)
        await message.answer(f"🗑 Задание ID {task_id} удалено.")
    except:
        await message.answer("❌ Ошибка! Формат: `/del ID_задания`", parse_mode="Markdown")

# Просмотр списка всех заданий с их ID
@dp.message(F.text == "/tasks", F.from_user.id == config.ADMIN_ID)
async def admin_list_tasks(message: types.Message):
    tasks = db.get_all_tasks()
    if not tasks:
        return await message.answer("📭 Список заданий пуст.")
    
    text = "📋 **Список всех заданий:**\n\n"
    for t in tasks:
        # t[0] - ID, t[1] - название, t[5] - время (если есть в базе)
        text += f"ID: `{t[0]}` — {t[1]} ({t[3]} ⭐)\n"
    
    text += "\nЧтобы удалить, пиши: `/del ID`"
    await message.answer(text, parse_mode="Markdown")

# --- НАЧИСЛЕНИЕ ЗВЕЗД ВРУЧНУЮ ---
@dp.message(F.text.startswith("/give"), F.from_user.id == config.ADMIN_ID)
async def admin_give_stars(message: types.Message):
    try:
        # Формат: /give ID_юзера Количество
        parts = message.text.split(" ")
        target_id = int(parts[1])
        amount = float(parts[2])
        
        db.update_balance(target_id, amount)
        
        await message.answer(f"✅ Начислено {amount} ⭐ пользователю `{target_id}`")
        # Уведомляем счастливчика
        try:
            await bot.send_message(target_id, f"🎁 Админ начислил вам {amount} ⭐!")
        except:
            pass 
    except:
        await message.answer("❌ Ошибка! Формат: `/give ID количество`", parse_mode="Markdown")

        
# --- КНОПКА СОТРУДНИЧЕСТВА (ДЛЯ ЮЗЕРОВ) ---
@dp.callback_query(F.data == "collab_request")
async def collab_start(call: types.CallbackQuery):
    await call.message.answer("Напиши свое предложение по сотрудничеству одним сообщением. Я передам его админу!")
    # Тут можно добавить состояние FSM, но для простоты сделаем через ожидание следующего сообщения в следующем шаге
    # Или просто оставь в описании текст. Но давай сделаем через кнопку:
    
# --- ПАНЕЛЬ УПРАВЛЕНИЯ (ТОЛЬКО ДЛЯ ТЕБЯ) ---
@dp.message(F.text == "/admin", F.from_user.id == config.ADMIN_ID)
async def admin_panel(message: types.Message):
    import sqlite3
    with sqlite3.connect("bot.db") as conn:
        users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_balance = conn.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
        tasks_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        pending_withdraws = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'pending'").fetchone()[0]

    stats_text = (
        f"🖥 **АДМИН-ПАНЕЛЬ**\n\n"
        f"👥 Всего юзеров: {users_count}\n"
        f"💰 Звезд в системе: {round(total_balance, 2)} ⭐\n"
        f"📢 Активных заданий: {tasks_count}\n"
        f"⏳ Ожидает вывода: {pending_withdraws}\n"
    )
    
    # Кнопки для быстрого управления
    admin_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📋 Список заданий", callback_data="adm_tasks_list")],
        [types.InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="adm_broadcast")]
    ])
    
    await message.answer(stats_text, reply_markup=admin_kb, parse_mode="Markdown")

# Обработка кнопки списка заданий из админки
@dp.callback_query(F.data == "adm_tasks_list")
async def adm_tasks_callback(call: types.CallbackQuery):
    if call.from_user.id != config.ADMIN_ID: return
    tasks = db.get_all_tasks()
    text = "📋 **Активные задания:**\n\n"
    for t in tasks:
        text += f"ID: `{t[0]}` | {t[1]} | {t[3]} ⭐\n"
    await call.message.answer(text, parse_mode="Markdown")

    
# --- ОБРАБОТКА КОМАНД И КНОПОК ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    # 1. Проверка на бота/аватарку (Анти-фрод)
    bad_msg = await is_bad_user(message)
    if bad_msg:
        return await message.answer(bad_msg)
    
    user_id = message.from_user.id
    ref_id = None
    
    # 2. Обработка реферальной ссылки
    if command.args and command.args.isdigit():
        if int(command.args) != user_id:
            ref_id = int(command.args)
    
    db.add_user(user_id, ref_id)
    
    # 3. Проверка обязательной подписки
    if not await check_main_subs(user_id):
        channels_str = "\n".join(config.REQUIRED_CHANNELS)
        return await message.answer(f"❌ Для работы с ботом подпишись на каналы:\n{channels_str}\n\nПосле подписки снова нажми /start")
    
    await message.answer(f"Привет! Зарабатывай ⭐ здесь.\nКурс: {config.EXCHANGE_RATE}", reply_markup=kb.main_menu())

@dp.callback_query(F.data == "profile")
async def profile(call: types.CallbackQuery):
    if not await check_main_subs(call.from_user.id):
        return await call.answer("❌ Подпишись на обязательные каналы!", show_alert=True)
        
    user = db.get_user(call.from_user.id)
    text = f"👤 Профиль\n\n💰 Баланс: {user[1]} ⭐\n💵 Примерно: {round(user[1] * 0.015, 2)}$"
    
    if user[1] >= config.MIN_WITHDRAW:
        await call.message.edit_text(text, reply_markup=kb.withdraw_currency_kb())
    else:
        await call.message.edit_text(text + f"\n\nДо вывода нужно еще {config.MIN_WITHDRAW - user[1]} ⭐", reply_markup=kb.main_menu())

@dp.callback_query(F.data == "refs")
async def refs_menu(call: types.CallbackQuery):
    if not await check_main_subs(call.from_user.id): return await call.answer("❌ Подпишись!", show_alert=True)
    
    import sqlite3
    with sqlite3.connect("bot.db") as conn:
        count = conn.execute("SELECT COUNT(*) FROM users WHERE ref_id = ?", (call.from_user.id,)).fetchone()[0]
    
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={call.from_user.id}"
    await call.message.edit_text(f"👥 Рефералы: {count} чел.\nБонус: {config.REF_BONUS*100}% от их дохода.\n\n🔗 Твоя ссылка:\n`{link}`", parse_mode="Markdown", reply_markup=kb.main_menu())

# --- ЛОГИКА ЗАДАНИЙ ---
@dp.callback_query(F.data == "tasks_list")
async def show_tasks(call: types.CallbackQuery):
    if not await check_main_subs(call.from_user.id): return await call.answer("❌ Подпишись!", show_alert=True)
    
    tasks = db.get_all_tasks()
    keyboard = []
    for t in tasks:
        if not db.is_task_completed(call.from_user.id, t[0]):
            keyboard.append([types.InlineKeyboardButton(text=f"{t[1]} ({t[3]} ⭐)", callback_data=f"view_task_{t[0]}")])
    
    keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")])
    await call.message.edit_text("Доступные задания:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("view_task_"))
async def view_task(call: types.CallbackQuery):
    task_id = int(call.data.split("_")[2])
    task = next((t for t in db.get_all_tasks() if t[0] == task_id), None)
    if task:
        await call.message.edit_text(f"Подпишись на {task[1]}\nНаграда: {task[3]} ⭐", reply_markup=kb.task_button(task[2], task[0]))

@dp.callback_query(F.data.startswith("check_"))
async def check_sub_task(call: types.CallbackQuery):
    task_id = int(call.data.split("_")[1])
    task = next((t for t in db.get_all_tasks() if t[0] == task_id), None)
    
    try:
        member = await bot.get_chat_member(chat_id=task[4], user_id=call.from_user.id)
        if member.status in ["member", "administrator", "creator"]:
            db.update_balance(call.from_user.id, task[3])
            db.complete_task(call.from_user.id, task_id)
            
            user_data = db.get_user(call.from_user.id)
            if user_data[2]: # Начисление рефереру
                db.update_balance(user_data[2], task[3] * config.REF_BONUS)
            
            await call.answer("✅ Начислено!", show_alert=True)
            await show_tasks(call)
        else:
            await call.answer("❌ Вы не подписаны!", show_alert=True)
    except:
        await call.answer("⚠️ Ошибка. Сообщите админу.", show_alert=True)


# --- РАЗДЕЛ КАЗИНО (СПЕЦ ЗАДАНИЯ) ---
@dp.callback_query(F.data == "high_reward")
async def high_reward_info(call: types.CallbackQuery):
    if not await check_main_subs(call.from_user.id): 
        return await call.answer("❌ Подпишись!", show_alert=True)
    
    text = (
        "🔥 *ЖИРНЫЙ КУШ (ОТ 50 ⭐)*\n\n"
        "Выполни спец-задания от наших партнеров:\n"
        "1. Зарегистрируйся в казино по ссылке: ТВОЯ_ССЫЛКА_ТУТ\n"
        "2. Сделай минимальный депозит.\n"
        "3. Сделай скриншот личного кабинета.\n\n"
        "📩 Скриншот и свой ID отправь менеджеру: @твой_твинк\n"
        "После проверки он начислит награду вручную!"
    )
    # Используем parse_mode="Markdown" (или "HTML", если хочешь надежнее)
    await call.message.edit_text(text, reply_markup=kb.main_menu())

# --- ВЫВОД ---
# Заявка на вывод с кнопками для админа
@dp.callback_query(F.data.startswith("out_"))
async def request_out(call: types.CallbackQuery):
    method = call.data.split("_")[1]
    user = db.get_user(call.from_user.id)
    user_id = call.from_user.id
    amount = user[1]

    if amount < config.MIN_WITHDRAW:
        return await call.answer(f"Минимум {config.MIN_WITHDRAW} ⭐", show_alert=True)

    # Кнопки для тебя (админа)
    admin_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="✅ Выплачено (Списать)", callback_data=f"adm_pay_{user_id}_{amount}"),
            types.InlineKeyboardButton(text="❌ Отказ", callback_data=f"adm_refuse_{user_id}")
        ]
    ])

    await bot.send_message(
        config.ADMIN_ID, 
        f"💰 **НОВАЯ ЗАЯВКА**\nЮзер: @{call.from_user.username}\nID: `{user_id}`\nСумма: {amount} ⭐\nМетод: {method}",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )
    await call.answer("✅ Заявка отправлена! Ожидайте выплаты.", show_alert=True)

# Обработка твоего решения (Админка)
@dp.callback_query(F.data.startswith("adm_"))
async def admin_decision(call: types.CallbackQuery):
    if call.from_user.id != config.ADMIN_ID: return
    
    action = call.data.split("_")[1]
    target_id = int(call.data.split("_")[2])

    if action == "pay":
        amount = float(call.data.split("_")[3])
        db.update_balance(target_id, -amount) # Списываем сумму (минус)
        await bot.send_message(target_id, f"✅ Твоя заявка на {amount} ⭐ одобрена! Деньги отправлены.")
        await call.message.edit_text(call.message.text + "\n\nСтатус: ✅ ВЫПЛАЧЕНО")
    
    elif action == "refuse":
        await bot.send_message(target_id, "❌ Твоя заявка на вывод отклонена. Обратись в поддержку.")
        await call.message.edit_text(call.message.text + "\n\nСтатус: ❌ ОТКАЗАНО")

# --- РЕКЛАМА ---
@dp.message(F.content_type == types.ContentType.WEB_APP_DATA)
async def ad_handler(message: types.Message):
    if message.web_app_data.data == "ad_watched":
        db.update_balance(message.from_user.id, config.AD_REWARD)
        await message.answer(f"✅ +{config.AD_REWARD} ⭐ за рекламу!")

# --- ФОНОВАЯ ЗАДАЧА (ОЧИСТКА ЗАДАНИЙ) ---
async def auto_delete_tasks():
    while True:
        try:
            db.delete_expired_tasks()
        except Exception as e:
            print(f"Ошибка очистки: {e}")
        await asyncio.sleep(600) # Проверка каждые 10 минут

async def start_bot():
    # Инициализация базы данных
    db.init_db()
    
    # Запуск фоновых задач
    asyncio.create_task(auto_delete_tasks())
    
    print("Бот Money Farm запущен!")
    
    # Запускаем «оживитель» для Replit
    keep_alive() 
    
    # Запуск самого бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
