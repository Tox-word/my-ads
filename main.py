import asyncio
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.exceptions import TelegramBadRequest

import config
import database as db
import kb

from flask import Flask
from threading import Thread

# --- КРУГЛОСУТОЧНАЯ РАБОТА (Keep Alive) ---
app = Flask('')

@app.route('/')
def home():
    return "Money Farm is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def check_main_subs(user_id: int):
    """Проверка обязательных каналов из конфига"""
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

async def is_bad_user(message: types.Message):
    """Анти-фрод: проверка аватарки и юзернейма"""
    try:
        photos = await bot.get_user_profile_photos(message.from_user.id)
        if photos.total_count == 0:
            return "❌ Ошибка: У вас нет фото профиля. Бот работает только с реальными аккаунтами."
        
        if not message.from_user.username:
            return "❌ Ошибка: У вас не установлен @username в настройках Telegram."
    except Exception:
        return "⚠️ Ошибка проверки аккаунта."
    return None

# --- АДМИН-КОМАНДЫ (УПРАВЛЕНИЕ ЗАДАНИЯМИ) ---

# 1. Добавление задания
@dp.message(F.text.startswith("/add "), F.from_user.id == config.ADMIN_ID)
async def admin_add_task(message: types.Message):
    try:
        # Формат: /add Название Ссылка Награда @юзернейм Часы
        parts = message.text.split(" ")
        title = parts[1]
        url = parts[2]
        reward = float(parts[3])
        chat_id = parts[4]
        hours = int(parts[5])
        
        expire_time = datetime.now() + timedelta(hours=hours)
        db.add_task(title, url, reward, chat_id, expire_time) 
        
        await message.answer(f"✅ Задание **'{title}'** добавлено!\n🕒 Истекает через: {hours} ч.\n💰 Награда: {reward} ⭐", parse_mode="Markdown")
    except Exception as e:
        await message.answer("❌ Ошибка! Формат: `/add Название Ссылка Награда @юзернейм ЧАСЫ`", parse_mode="Markdown")

# 2. Удаление задания по ID
@dp.message(F.text.startswith("/del "), F.from_user.id == config.ADMIN_ID)
async def admin_del_task(message: types.Message):
    try:
        task_id = int(message.text.split(" ")[1])
        db.delete_task(task_id)
        await message.answer(f"🗑 Задание ID `{task_id}` удалено из базы.", parse_mode="Markdown")
    except:
        await message.answer("❌ Ошибка! Формат: `/del ID_задания`", parse_mode="Markdown")

# 3. Список всех заданий (для админа)
@dp.message(F.text == "/tasks", F.from_user.id == config.ADMIN_ID)
@dp.callback_query(F.data == "adm_tasks_list") # Добавляем обработку кнопки из админки
async def admin_list_tasks(event: types.Message | types.CallbackQuery):
    # Если это кнопка — берем message из call, если команда — само сообщение
    message = event if isinstance(event, types.Message) else event.message
    
    tasks = db.get_all_tasks()
    if not tasks:
        text = "📭 Список активных заданий пуст."
    else:
        text = "📋 **СПИСОК ВСЕХ ЗАДАНИЙ:**\n\n"
        for t in tasks:
            # t[0]-ID, t[1]-title, t[3]-reward
            text += f"🔹 ID: `{t[0]}` | {t[1]} ({t[3]} ⭐)\n"
        text += "\nУдалить: `/del ID`"
    
    # Если это кнопка, лучше редактировать текст, а не слать новый
    if isinstance(event, types.CallbackQuery):
        await message.edit_text(text, parse_mode="Markdown", reply_markup=kb.admin_panel_kb())
        await event.answer()
    else:
        await message.answer(text, parse_mode="Markdown")

# --- УПРАВЛЕНИЕ БАЛАНСОМ (РУЧНОЕ) ---

@dp.message(F.text.startswith("/give "), F.from_user.id == config.ADMIN_ID)
async def admin_give_stars(message: types.Message):
    try:
        # Формат: /give ID_юзера Количество
        parts = message.text.split(" ")
        target_id = int(parts[1])
        amount = float(parts[2])
        
        db.update_balance(target_id, amount)
        
        await message.answer(f"✅ Успешно! Начислено {amount} ⭐ пользователю `{target_id}`")
        # Уведомление пользователю
        try:
            await bot.send_message(target_id, f"🎁 Админ начислил вам бонус: {amount} ⭐!")
        except:
            pass 
    except:
        await message.answer("❌ Ошибка! Формат: `/give ID количество`", parse_mode="Markdown")

# --- ПАНЕЛЬ УПРАВЛЕНИЯ (ТОЛЬКО ДЛЯ ТЕБЯ) ---
@dp.message(F.text == "/admin", F.from_user.id == config.ADMIN_ID)
async def admin_panel(message: types.Message):
    # Берем данные через новые функции базы (Postgres)
    stats = db.get_admin_stats() # Должна возвращать (users, balance, tasks, withdraws)
    
    stats_text = (
        f"🖥 **АДМИН-ПАНЕЛЬ**\n\n"
        f"👥 Всего юзеров: {stats['users_count']}\n"
        f"💰 Звезд в системе: {round(stats['total_balance'], 2)} ⭐\n"
        f"📢 Активных заданий: {stats['tasks_count']}\n"
        f"⏳ Ожидает вывода: {stats['pending_withdraws']}\n"
    )
    
    admin_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📋 Список заданий", callback_data="adm_tasks_list")],
        [types.InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="adm_broadcast")]
    ])
    
    await message.answer(stats_text, reply_markup=admin_kb, parse_mode="Markdown")

# --- ОБРАБОТКА КОМАНДЫ /START ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    # 1. Анти-фрод (Проверка аватара/юзернейма)
    bad_msg = await is_bad_user(message)
    if bad_msg:
        return await message.answer(bad_msg)
    
    user_id = message.from_user.id
    
    # Получаем данные юзера из базы ДО регистрации
    existing_user = db.get_user(user_id)
    
    # 2. Логика реферальной ссылки
    ref_id = None
    if not existing_user and command.args and command.args.isdigit():
        if int(command.args) != user_id:
            ref_id = int(command.args)
    
    # Регистрация (Функция должна возвращать True если юзер реально новый)
    is_new = db.add_user(user_id, ref_id)
    
    # 3. Проверка обязательной подписки (ОП)
    is_subscribed = await check_main_subs(user_id)
    
    if not is_subscribed:
        channels_str = "\n".join(config.REQUIRED_CHANNELS)
        return await message.answer(
            f"❌ Для работы с ботом подпишись на каналы:\n{channels_str}\n\n"
            f"После подписки снова нажми /start"
        )

    # --- ПУНКТ 2: УВЕДОМЛЕНИЕ ПОСЛЕ ПОДПИСКИ ---
    # Если юзер только что прошел проверку ОП и он новый
    if is_new:
        # Здесь можно добавить пометку в базу, что юзер "активирован"
        # Но для начала просто уведомим реферера
        if ref_id:
            try:
                await bot.send_message(
                    chat_id=ref_id,
                    text=f"👥 **Новый активный реферал!**\n"
                         f"Пользователь @{message.from_user.username} подписался на каналы и принес вам бонус!"
                )
            except:
                pass

    await message.answer(
        f"Привет на ферме! Зарабатывай ⭐ здесь.\nКурс: {config.EXCHANGE_RATE}", 
        reply_markup=kb.main_menu()
    )


# --- ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ---
@dp.callback_query(F.data == "profile")
async def profile(call: types.CallbackQuery):
    if not await check_main_subs(call.from_user.id):
        return await call.answer("❌ Сначала подпишись на каналы!", show_alert=True)
        
    user = db.get_user(call.from_user.id) # Возвращает [id, balance, ref_id...]
    balance = user[1]
    
    # Пересчет в доллары (твой старый курс 0.015)
    usd_val = round(balance * 0.015, 2)
    
    text = f"👤 **ПРОФИЛЬ**\n\n💰 Баланс: {balance} ⭐\n💵 Примерно: {usd_val}$"
    
    if balance >= config.MIN_WITHDRAW:
        await call.message.edit_text(text, reply_markup=kb.withdraw_currency_kb())
    else:
        await call.message.edit_text(
            text + f"\n\nДо вывода нужно еще {config.MIN_WITHDRAW - balance} ⭐", 
            reply_markup=kb.main_menu()
        )

# --- ЛОГИКА ЗАДАНИЙ (ОТОБРАЖЕНИЕ) ---

@dp.callback_query(F.data == "tasks_list")
async def show_tasks(call: types.CallbackQuery):
    if not await check_main_subs(call.from_user.id): 
        return await call.answer("❌ Сначала подпишись на ОП!", show_alert=True)
    
    tasks = db.get_all_tasks()
    keyboard = []
    for t in tasks:
        # t[0] - ID, t[1] - Название, t[3] - Награда
        if not db.is_task_completed(call.from_user.id, t[0]):
            keyboard.append([types.InlineKeyboardButton(
                text=f"{t[1]} ({t[3]} ⭐)", 
                callback_data=f"view_task_{t[0]}"
            )])
    
    keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")])
    await call.message.edit_text("🎯 Доступные задания:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("view_task_"))
async def view_task(call: types.CallbackQuery):
    task_id = int(call.data.split("_")[2])
    task = next((t for t in db.get_all_tasks() if t[0] == task_id), None)
    if task:
        # task[1] - Название, task[3] - Награда, task[2] - Ссылка
        await call.message.edit_text(
            f"📢 **Задание:** {task[1]}\n💰 **Награда:** {task[3]} ⭐\n\n"
            f"Подпишись на канал по ссылке ниже и нажми 'Проверить'.",
            reply_markup=kb.task_button(task[2], task[0]),
            parse_mode="Markdown"
        )

# --- ПРОВЕРКА ВЫПОЛНЕНИЯ И НАЧИСЛЕНИЕ (2 УРОВНЯ РЕФКИ) ---

@dp.callback_query(F.data.startswith("check_"))
async def check_sub_task(call: types.CallbackQuery):
    task_id = int(call.data.split("_")[1])
    task = next((t for t in db.get_all_tasks() if t[0] == task_id), None)
    user_id = call.from_user.id
    
    try:
        # task[4] - это chat_id канала (например @mychannel)
        member = await bot.get_chat_member(chat_id=task[4], user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            # 1. Начисляем юзеру за задание
            db.update_balance(user_id, task[3])
            db.complete_task(user_id, task_id)
            
            # 2. РЕФЕРАЛЬНЫЕ НАЧИСЛЕНИЯ (L1 - 15%, L2 - 10%)
            user_data = db.get_user(user_id) # [id, balance, ref_id...]
            parent_id = user_data[2] # Кто пригласил юзера
            
            if parent_id:
                # Начисляем Папе (L1)
                reward_l1 = task[3] * 0.15
                db.update_balance(parent_id, reward_l1)
                
                # Ищем Дедушку (L2)
                parent_data = db.get_user(parent_id)
                grandpa_id = parent_data[2] if parent_data else None
                
                if grandpa_id:
                    # Начисляем Дедушке (L2)
                    reward_l2 = task[3] * 0.10
                    db.update_balance(grandpa_id, reward_l2)
            
            await call.answer("✅ Задание выполнено! Звезды начислены.", show_alert=True)
            await show_tasks(call) # Возврат к списку
        else:
            await call.answer("❌ Вы еще не подписались на этот канал!", show_alert=True)
    except Exception:
        await call.answer("⚠️ Ошибка проверки. Возможно, бот не админ в том канале.", show_alert=True)

# --- СИСТЕМА ВЫВОДА СРЕДСТВ ---

@dp.callback_query(F.data.startswith("out_"))
async def request_out(call: types.CallbackQuery):
    method = call.data.split("_")[1] # TON, Stars и т.д.
    user = db.get_user(call.from_user.id)
    amount = user[1]

    if amount < config.MIN_WITHDRAW:
        return await call.answer(f"❌ Минимум для вывода: {config.MIN_WITHDRAW} ⭐", show_alert=True)

    # Кнопки для админа (тебя) в личку
    admin_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="✅ Выплачено", callback_data=f"adm_pay_{call.from_user.id}_{amount}"),
            types.InlineKeyboardButton(text="❌ Отказ", callback_data=f"adm_refuse_{call.from_user.id}")
        ]
    ])

    await bot.send_message(
        config.ADMIN_ID, 
        f"💰 **ЗАЯВКА НА ВЫВОД**\n"
        f"👤 Юзер: @{call.from_user.username} (ID: `{call.from_user.id}`)\n"
        f"💎 Сумма: **{amount} ⭐**\n"
        f"🏦 Метод: {method.upper()}",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )
    await call.answer("✅ Заявка отправлена админу. Ожидайте!", show_alert=True)


# --- ОБРАБОТКА РЕШЕНИЙ АДМИНА ПО ВЫПЛАТАМ ---

@dp.callback_query(F.data.startswith("adm_"))
async def admin_decision(call: types.CallbackQuery):
    if call.from_user.id != config.ADMIN_ID: return
    
    parts = call.data.split("_")
    action = parts[1] # pay или refuse
    target_id = int(parts[2])

    if action == "pay":
        amount = float(parts[3])
        db.update_balance(target_id, -amount) # Списание баланса (минус сумма)
        
        try:
            await bot.send_message(target_id, f"✅ Твоя заявка на {amount} ⭐ одобрена! Деньги отправлены.")
        except: pass
        
        await call.message.edit_text(call.message.text + "\n\n**Статус:** ✅ ВЫПЛАЧЕНО", parse_mode="Markdown")
    
    elif action == "refuse":
        try:
            await bot.send_message(target_id, "❌ Твоя заявка на вывод отклонена. Обратись в поддержку.")
        except: pass
        
        await call.message.edit_text(call.message.text + "\n\n**Статус:** ❌ ОТКАЗАНО", parse_mode="Markdown")

# --- ЕЖЕДНЕВНЫЙ БОНУС (ЧЕК-ИН) ---

@dp.callback_query(F.data == "daily_bonus")
async def daily_checkin(call: types.CallbackQuery):
    user = db.get_user(call.from_user.id) # [id, balance, ref_id, last_checkin, streak]
    last_checkin = user[3]
    streak = user[4] or 0
    now = datetime.now()

    if last_checkin and (now - last_checkin) < timedelta(days=1):
        remaining = (last_checkin + timedelta(days=1)) - now
        hours = remaining.seconds // 3600
        mins = (remaining.seconds // 60) % 60
        return await call.answer(f"⏳ Жди еще {hours}ч. {mins}мин.", show_alert=True)

    # Если пропустил больше 2 дней — сброс на 1, иначе +1 (макс 10)
    new_streak = streak + 1 if (not last_checkin or (now - last_checkin) <= timedelta(days=2)) and streak < 10 else 1
    
    reward = round(new_streak * 0.1, 1) # Награда растет с каждым днем
    db.update_balance(call.from_user.id, reward)
    db.update_checkin(call.from_user.id, new_streak)
    
    await call.message.answer(f"✅ День {new_streak}: Получено {reward} ⭐!", reply_markup=kb.main_menu())

# --- ПРОМОКОДЫ ---

@dp.message(Command("promo"))
async def use_promo_cmd(message: types.Message, command: CommandObject):
    if not command.args:
        return await message.answer("❓ **Как ввести код:**\nНапишите: `/promo ТВОЙ_КОД`", parse_mode="Markdown")

    code_text = command.args.strip()
    user_id = message.from_user.id
    promo = db.get_promo(code_text)
    
    if not promo or promo[2] <= 0:
        return await message.answer("❌ Промокод не существует или закончился.")
    
    # ПРОВЕРКА: Делал ли он это раньше? (promo_ID)
    p_id = f"p_{code_text}"
    if db.check_task_completed(user_id, p_id):
        return await message.answer("🚫 Вы уже использовали этот код!")

    # Начисляем
    db.update_balance(user_id, promo[1])
    db.use_promo(code_text)
    db.add_completed_task(user_id, p_id) # Блокируем повтор
    
    await message.answer(f"✅ Успешно! +{promo[1]} ⭐")


# --- ОБРАБОТКА КНОПКИ РЕФЕРАЛЫ ---
@dp.callback_query(F.data == "refs")
async def show_refs(call: types.CallbackQuery):
    user_id = call.from_user.id
    count = db.get_refs_count(user_id)
    link = f"https://t.me/{(await bot.get_me()).username}?start={user_id}"
    
    text = (
        f"👥 **ВАШИ РЕФЕРАЛЫ**\n\n"
        f"📈 Уровень 1 (15%): {count} чел.\n"
        f"🔗 Ваша ссылка для приглашения:\n`{link}`\n\n"
        f"Приглашайте друзей и получайте процент от их заработка!"
    )
    await call.message.edit_text(text, reply_markup=kb.main_menu(), parse_mode="Markdown")


# --- НОВАЯ БЕЗОПАСНАЯ РАССЫЛКА ---
@dp.message(F.text.startswith("/send "), F.from_user.id == config.ADMIN_ID)
async def admin_broadcast_cmd(message: types.Message):
    broadcast_text = message.text.replace("/send ", "").strip()
    if not broadcast_text:
        return await message.answer("❌ Напиши: `/send Твой текст`")
    
    users = db.get_all_users()
    count = 0
    await message.answer("🚀 Начинаю рассылку...")
    
    for user in users:
        try:
            await bot.send_message(user[0], broadcast_text)
            count += 1
            await asyncio.sleep(0.05) # Защита от бана
        except:
            continue
            
    await message.answer(f"✅ Рассылка завершена! Получили: {count} чел.")

# Чтобы бот не реагировал на обычные сообщения:
@dp.message(F.from_user.id == config.ADMIN_ID, ~F.text.startswith("/"))
async def ignore_admin_text(message: types.Message):
    # Просто ничего не делаем или отвечаем эхом, чтобы не было рассылки
    pass

# --- ДОПОЛНЕНИЕ: ПРОМОКОДЫ ---
@dp.message(F.text.startswith("/add_promo"), F.from_user.id == config.ADMIN_ID)
async def admin_add_promo(message: types.Message):
    try:
        # Разбиваем сообщение, игнорируя лишние пробелы
        parts = message.text.split()
        
        if len(parts) < 4:
            return await message.answer("❌ Формат: `/add_promo КОД КОЛ_ВО НАГРАДА @канал`", parse_mode="Markdown")

        code = parts[1]
        uses = int(parts[2])
        # Обработка награды (замена запятой на точку для float)
        reward = float(parts[3].replace(",", "."))
        # Канал — 5-й элемент (если есть)
        channel = parts[4] if len(parts) > 4 else None
        
        # ВЫЗОВ ТВОЕЙ ФУНКЦИИ (название должно совпадать с database.py)
        db.add_promo_to_db(code, reward, uses, channel)
        
        await message.answer(
            f"✅ **Промокод готов!**\n\n"
            f"🎫 Код: `{code}`\n"
            f"💰 Награда: {reward} ⭐\n"
            f"👥 Лимит: {uses} чел.\n"
            f"📢 Канал: {channel if channel else 'Нет'}",
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Ошибка: КОЛ_ВО и НАГРАДА должны быть числами (например: 50 0.5)")
    except Exception as e:
        print(f"Ошибка промокода: {e}")
        await message.answer("⚠️ Что-то пошло не так. Проверь логи или формат команды.")


# --- ОБРАБОТКА КНОПКИ СПЕЦ-ЗАДАНИЯ ---
@dp.callback_query(F.data == "high_reward")
async def high_reward_tasks(call: types.CallbackQuery):
    await call.answer("🔥 Спец-задания появятся скоро!", show_alert=True)

# --- ВЫВОД ---

# 1. Нажатие на "Вывести" в профиле
@dp.callback_query(F.data == "withdraw_request")
async def start_withdraw(call: types.CallbackQuery):
    user = db.get_user(call.from_user.id)
    if user[2] < 200: # Твой порог в 200 звезд
        return await call.answer(f"❌ Минимум 200 ⭐ (у вас {user[2]})", show_alert=True)
    
    await call.message.edit_text("💳 **Выберите способ вывода:**", reply_markup=kb.withdraw_methods_kb())

# 2. Выбор метода
@dp.callback_query(F.data.startswith("meth_"))
async def choose_method(call: types.CallbackQuery):
    method = call.data.split("_")[1].upper()
    prompt = {
        "TON": "Введите ваш TON адрес (кошелек):",
        "USD": "Введите данные для USD вывода (PayPal/Card/Crypto):",
        "STARS": "Введите @username или ID аккаунта для перевода звезд:"
    }
    
    # Сохраняем метод в "память" (простой способ без FSM для админа)
    await call.message.answer(f"✅ Вы выбрали {method}.\n{prompt.get(method)}\n\n(Просто отправьте данные следующим сообщением)")
    await call.answer()

# 3. Прием реквизитов и отправка админу (тебе)
@dp.message(F.text, ~F.text.startswith("/")) # Если это просто текст, а не команда
async def process_withdraw_data(message: types.Message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    # Проверяем баланс еще раз на всякий случай
    if user[2] < 200:
        return # Игнорим, если баланса нет
    
    # Формируем заявку для ТЕБЯ
    admin_text = (
        f"💰 **НОВАЯ ЗАЯВКА НА ВЫВОД!**\n\n"
        f"👤 Юзер: @{message.from_user.username} (ID: `{user_id}`)\n"
        f"💎 Баланс: {user[2]} ⭐\n"
        f"📝 Реквизиты: `{message.text}`\n\n"
        f"Чтобы выдать, используй: `/give {user_id} -200`"
    )
    
    # Отправляем тебе
    await bot.send_message(config.ADMIN_ID, admin_text, parse_mode="Markdown")
    
    # Ответ юзеру
    await message.answer("✅ **Заявка принята!**\nАдмин проверит данные и произведет выплату в течение 24 часов.")


    
# --- ФОНОВАЯ ЗАДАЧА И ЗАПУСК ---

async def auto_delete_tasks():
    while True:
        try: db.delete_expired_tasks()
        except: pass
        await asyncio.sleep(600)


async def start_bot():
    db.init_db()
    asyncio.create_task(auto_delete_tasks())
    keep_alive()
    print("Money Farm Bot Started on Postgres!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except (KeyboardInterrupt, SystemExit):
        print("Bot Stopped")
