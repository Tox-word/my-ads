import asyncio
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.exceptions import TelegramBadRequest

import config
import database as db
import kb

from flask import Flask
from threading import Thread

# Временное хранилище заявок: {user_id: {'method': 'TON', 'amount': 200}}
withdraw_cache = {}

# Временное хранилище промокодов
promo_cache = {} # В начало файла к withdraw_cache

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
        
@dp.message(Command("add_promo"), F.from_user.id == config.ADMIN_ID)
async def admin_add_promo(message: types.Message, command: CommandObject):
    try:
        # Формат: /add_promo КОД СУММА КОЛ-ВО
        args = command.args.split()
        code = args[0].upper()
        reward = float(args[1])
        uses = int(args[2])
        
        db.add_promo(code, reward, uses) # Убедись, что в database.py есть эта функция
        await message.answer(f"✅ Промокод `{code}` на {reward} ⭐ создан! (Лимит: {uses})")
    except:
        await message.answer("❌ Ошибка! Пиши: `/add_promo СЕКРЕТ 50 100`")

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
    try:
        user_id = message.from_user.id
        
        # 1. Анти-фрод (проверка фото и юзернейма)
        bad_msg = await is_bad_user(message)
        if bad_msg:
            return await message.answer(bad_msg)
        
        # 2. Регистрация (проверяем, новый ли юзер)
        existing_user = db.get_user(user_id)
        ref_id = None
        
        if not existing_user:
            # Если пришел по ссылке: /start 12345
            if command.args and command.args.isdigit():
                if int(command.args) != user_id:
                    ref_id = int(command.args)
            db.add_user(user_id, ref_id)
        
        # 3. Проверка обязательной подписки
        is_subscribed = await check_main_subs(user_id)
        if not is_subscribed:
            channels_str = "\n".join(config.REQUIRED_CHANNELS)
            return await message.answer(
                f"❌ Для работы с ботом подпишись на каналы:\n{channels_str}\n\n"
                f"После подписки снова нажми /start"
            )

# 4. Начисление бонуса пригласившему
        user_data = db.get_user(user_id)
        
        # Проверяем: юзер есть в базе и бонус за него ЕЩЕ НЕ ВЫДАВАЛИ
        if user_data and not user_data[6]: 
            actual_ref_id = user_data[2] # Берем того, кто пригласил
            
            if actual_ref_id:
                # Начисляем Папе (L1) + обновляем статистику (True)
                db.update_balance(actual_ref_id, 5.0, True) 
                
                # Ищем Дедушку (L2)
                parent_data = db.get_user(actual_ref_id)
                if parent_data and parent_data[2]:
                    # Начисляем Дедушке (L2) + обновляем статистику (True)
                    db.update_balance(parent_data[2], 1.0, True)
                
                try:
                    await bot.send_message(actual_ref_id, "👥 **Новый активный реферал!**\n💰 +5.0 ⭐", parse_mode="Markdown")
                except:
                    pass
            
            # ВАЖНО: Ставим отметку, чтобы бонус не выдался второй раз
            db.mark_bonus_given(user_id)

        # 5. Главное меню
        await message.answer(
            f"✅ Добро пожаловать в **Money Farm**!\nЗарабатывай звезды, выполняя задания.", 
            reply_markup=kb.main_menu(), 
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"ОШИБКА В /START: {e}")
        await message.answer("⚠️ Произошла ошибка. Попробуй позже.")

# --- НАЧИСЛЕНИЕ ЗА РЕФЕРАЛА (ВСТАВЛЯТЬ СЮДА) ---
    
    # 1. Получаем свежие данные юзера из базы
    user_data = db.get_user(user_id)
    # ПРОВЕРЬ ИНДЕКС: если в таблице users колонка ref_bonus_given 
    # идет шестой по счету, то индекс будет [5]
    bonus_already_given = user_data[6] if user_data else True 

    # 2. Проверяем: подписан ли он И не давали ли мы за него бонус ранее
    if is_subscribed and not bonus_already_given:
        # Достаем того, кто его пригласил
        actual_ref_id = user_data[2] if user_data else None
        
        if actual_ref_id:
            # Начисляем Папе (L1)
            db.update_balance(actual_ref_id, 5.0)
            
            # Ищем Дедушку (L2)
            parent_data = db.get_user(actual_ref_id)
            if parent_data and parent_data[2]:
                db.update_balance(parent_data[2], 1.0)
            
            # Уведомляем Папу
            try:
                await bot.send_message(
                    actual_ref_id, 
                    "👥 **У вас новый активный реферал!**\n💰 Вам начислено: **5.0 ⭐**", 
                    parse_mode="Markdown"
                )
            except:
                pass
        
        # СТАВИМ ГАЛОЧКУ: бонус за этого юзера выдан, больше не платим
        db.mark_bonus_given(user_id)

    # 4. Финальный ответ: Главное меню
    await message.answer(f"✅ Подписка подтверждена! Добро пожаловать в Money Farm!", reply_markup=kb.main_menu())

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


# Рефка
@dp.callback_query(F.data.startswith("check_"))
async def check_sub_task(call: types.CallbackQuery):
    task_id = int(call.data.split("_")[1])
    user_id = call.from_user.id

    # 1. ПРОВЕРКА: Не выполнял ли юзер это задание раньше?
    if db.is_task_completed(user_id, task_id):
        return await call.answer("🚫 Вы уже получили награду за это задание!", show_alert=True)

    # Получаем данные о задании
    task = next((t for t in db.get_all_tasks() if t[0] == task_id), None)
    if not task:
        return await call.answer("⚠️ Задание не найдено.", show_alert=True)
    
    try:
        # Проверка подписки в канале (task[4] — это ID или @канала)
        member = await bot.get_chat_member(chat_id=task[4], user_id=user_id)
        
        if member.status in ["member", "administrator", "creator"]:
            reward = task[3] # Основная награда юзеру
            
            # 2. НАЧИСЛЯЕМ ЮЗЕРУ
            db.update_balance(user_id, reward)
            db.complete_task(user_id, task_id) # Помечаем как выполненное В БАЗЕ
            
            # 3. РЕФЕРАЛЬНЫЕ НАЧИСЛЕНИЯ
            user_data = db.get_user(user_id)
            parent_id = user_data[2] if user_data else None # Тот, кто пригласил
            
            if parent_id:
                # Начисляем Папе (L1) — 10%
                reward_l1 = round(reward * 0.10, 2)
                db.update_balance(parent_id, reward_l1)
                
                # Ищем Дедушку (L2) — 5%
                parent_data = db.get_user(parent_id)
                grandpa_id = parent_data[2] if parent_data else None
                
                if grandpa_id:
                    reward_l2 = round(reward * 0.05, 2)
                    db.update_balance(grandpa_id, reward_l2)
            
            await call.answer("✅ Задание выполнено! Звезды начислены.", show_alert=True)
            # Обновляем сообщение со списком заданий, чтобы выполненное исчезло (или пометилось)
            await show_tasks(call) 
            
        else:
            await call.answer("❌ Вы еще не подписались на канал!", show_alert=True)
            
    except Exception as e:
        print(f"Ошибка проверки подписки: {e}")
        await call.answer("⚠️ Бот не может проверить подписку. Убедитесь, что бот — админ в канале.", show_alert=True)

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

# --- ОБРАБОТКА КНОПКИ РЕФЕРАЛЫ ---
@dp.callback_query(F.data == "refs")
async def show_refs(call: types.CallbackQuery):
    l1, l2 = db.get_detailed_refs(call.from_user.id)
    link = f"https://t.me/{(await bot.get_me()).username}?start={call.from_user.id}"
    
    text = (
        f"👥 **ВАША КОМАНДА**\n\n"
        f"🥇 **Уровень 1:**\n"
        f"├ Рефералов: **{l1}** чел.\n"
        f"└ Бонус: **+5.0 ⭐** за вход + **10%** с заданий\n\n"
        f"🥈 **Уровень 2:**\n"
        f"├ Рефералов: **{l2}** чел.\n"
        f"└ Бонус: **+1.0 ⭐** за вход + **5%** с заданий\n\n"
        f"🔗 **Ваша ссылка:**\n"
        f"`{link}`"
    )
    # Проверь, чтобы await был ровно под text
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

# --- ОБРАБОТКА КНОПКИ СПЕЦ-ЗАДАНИЯ ---
@dp.callback_query(F.data == "high_reward")
async def high_reward_tasks(call: types.CallbackQuery):
    await call.answer("🔥 Спец-задания появятся скоро!", show_alert=True)

# --- ПРОМОКОДЫ: ОБРАБОТКА (КНОПКА В МЕНЮ И ИНЛАЙН) ---

# Если нажали кнопку в обычном меню
@dp.message(F.text == "🎫 Промокод")
async def promo_menu_handler(message: types.Message):
    # Сбрасываем кэш вывода, если он был, чтобы не мешал
    if message.from_user.id in withdraw_cache: del withdraw_cache[message.from_user.id]
    
    promo_cache[message.from_user.id] = True
    withdraw_cache.pop(message.from_user.id, None)  # ← ВОТ ЭТО ДОБАВЬ
    await message.answer("🎟 **Введите ваш промокод:**", parse_mode="Markdown")

# Если нажали инлайн-кнопку (из профиля или заданий)
@dp.callback_query(F.data == "promo_activate")
async def promo_callback_handler(call: types.CallbackQuery):
    if call.from_user.id in withdraw_cache: del withdraw_cache[call.from_user.id]
    
    promo_cache[call.from_user.id] = True
    withdraw_cache.pop(call.from_user.id, None)  # ← ДОБАВЬ
    await call.message.answer("🎟 **Введите ваш промокод:**", parse_mode="Markdown")
    await call.answer()


# --- ВЫВОД: ВЫБОР МЕТОДА ---

@dp.callback_query(F.data.startswith("meth_"))
async def choose_method(call: types.CallbackQuery):
    # Сбрасываем кэш промокода, если юзер решил вместо него вывести деньги
    if call.from_user.id in promo_cache: del promo_cache[call.from_user.id]
    
    method = call.data.split("_")[1].upper()
    withdraw_cache[call.from_user.id] = {'method': method}
    promo_cache.pop(call.from_user.id, None)  # ← ДОБАВЬ
    
    await call.message.answer(
        f"✅ Выбран метод: **{method}**\n\n"
        f"**Шаг 1:** Введите количество ⭐ для вывода (минимум 200):",
        parse_mode="Markdown"
    )
    await call.answer()


@dp.message(F.text, ~F.text.startswith("/"))
async def handle_all_text(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    user_data = db.get_user(user_id)
    if not user_data:
        return

    # =========================
    # 🔴 1. ВЫВОД (ПРИОРИТЕТ)
    # =========================
    if user_id in withdraw_cache:
        data = withdraw_cache[user_id]

        # ШАГ 1: сумма
        if 'amount' not in data:
            if not text.isdigit():
                return await message.answer("❌ Введите число!")

            amount = int(text)

            if amount < 200:
                return await message.answer("❌ Минимум 200 ⭐")

            if amount > user_data[1]:
                return await message.answer(f"❌ Недостаточно звезд! У вас: {user_data[1]} ⭐")

            withdraw_cache[user_id]['amount'] = amount
            return await message.answer("💳 Введите реквизиты:")

        # ШАГ 2: реквизиты
        else:
            method = data['method']
            amount = data['amount']

            success = db.update_balance(user_id, -amount)
            if not success:
                withdraw_cache.pop(user_id, None)
                return await message.answer("❌ Ошибка списания. Попробуйте снова.")

            admin_kb = types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(text="✅ Выплатить", callback_data=f"adm_pay_{user_id}_{amount}"),
                types.InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_refuse_{user_id}_{amount}")
            ]])

            await bot.send_message(
                config.ADMIN_ID,
                f"🚀 Вывод {amount} ⭐\nЮзер: {user_id}\nРеквизиты: {text}",
                reply_markup=admin_kb
            )

            await message.answer("✅ Заявка отправлена!")
            withdraw_cache.pop(user_id, None)
            return

    # =========================
    # 🟡 2. ЛОГИКА ПРОМОКОДА
    # =========================
    if promo_cache.get(user_id):
        code = text.upper()
        promo = db.get_promo(code) # Получаем (Код, Код, Награда, 1, Статус)

        if not promo:
            await message.answer("❌ Такого промокода нет.")
        elif promo[4] == 1: # Проверка: закончились ли использования
            await message.answer("❌ Промокод закончился.")
        else:
            # Проверяем, не юзал ли юзер его раньше (с префиксом PROMO_)
            if db.is_promo_used(user_id, code):
                await message.answer("🚫 Вы уже использовали этот код.")
            else:
                # Используем награду из promo[2]
                reward = promo[2]
                
                # Вызываем функцию из базы, которая сама всё начислит и спишет
                db.use_promo(user_id, code, reward)
                
                await message.answer(f"✅ Начислено {reward} ⭐")

        # Обязательно убираем юзера из режима ожидания текста
        promo_cache.pop(user_id, None)
        return

    # =========================
    # ⚪ 3. ЕСЛИ НИЧЕГО
    # =========================
    await message.answer("❓ Используй кнопки меню.")


@dp.callback_query(F.data.startswith("adm_"))
async def admin_decision(call: types.CallbackQuery):
    if call.from_user.id != int(config.ADMIN_ID): return
    parts = call.data.split("_")
    action, target_id, amount = parts[1], int(parts[2]), float(parts[3])

    if action == "pay":
        try: await bot.send_message(target_id, f"✅ Выплата {amount} ⭐ одобрена!")
        except: pass
        await call.message.edit_text(call.message.text + "\n✅ ВЫПЛАЧЕНО")
    elif action == "refuse":
        db.update_balance(target_id, amount) # ВОЗВРАТ
        try: await bot.send_message(target_id, f"❌ Вывод {amount} ⭐ отклонен, возврат.")
        except: pass
        await call.message.edit_text(call.message.text + "\n❌ ОТКАЗАНО")
    await call.answer()

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
