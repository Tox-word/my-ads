import asyncio
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import config
import database as db
import kb

from flask import Flask
from threading import Thread

# --- СОСТОЯНИЯ (Решает конфликт Промо/Вывод) ---
class WithdrawState(StatesGroup):
    wait_amount = State()   # Ждем ввода суммы
    wait_details = State()  # Ждем ввода реквизитов

# Временное хранилище для промокодов (оставляем простым)
promo_cache = {} 


async def main():
    # --- БЛОК ОЧИСТКИ БАЗЫ (УДАЛИТЬ ПОСЛЕ ПЕРВОГО ЗАПУСКА) ---
    with db.get_connection() as conn:
        cur = conn.cursor()
        try:
            print("⏳ Начинаю полную очистку базы данных...")
            # Удаляем все таблицы, учитывая связи (CASCADE)
            cur.execute("DROP TABLE IF EXISTS users, tasks, completed_tasks, withdrawals, promos CASCADE")
            conn.commit()
            print("🗑 Все таблицы удалены.")
            
            # Сразу вызываем инициализацию новых таблиц
            db.init_db()
            print("✅ База данных успешно пересоздана с нуля!")
        except Exception as e:
            print(f"❌ Ошибка при очистке: {e}")
            conn.rollback()
    # --- КОНЕЦ БЛОКА ОЧИСТКИ ---

async def main():
    # --- ПРОВЕРКА И ОБНОВЛЕНИЕ СТРУКТУРЫ БД ---
    with db.get_connection() as conn:
        cur = conn.cursor()
        try:
            # Пытаемся добавить колонку, если её нет
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_bonus_given BOOLEAN DEFAULT FALSE")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_ref_earned REAL DEFAULT 0")
            conn.commit()
            print("✅ База данных проверена и обновлена")
        except Exception as e:
            print(f"⚠️ Ошибка при обновлении таблиц: {e}")
            conn.rollback()

# --- KEEP ALIVE (Для Render) ---
app = Flask('')
@app.route('/')
def home(): return "Money Farm is running!"

def run(): app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=config.BOT_TOKEN)
# MemoryStorage нужен для работы состояний (FSM)
dp = Dispatcher(storage=MemoryStorage())

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def check_main_subs(user_id: int):
    """Проверка обязательных каналов из config.py"""
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
        # У админа не проверяем
        if message.from_user.id == config.ADMIN_ID:
            return None
            
        photos = await bot.get_user_profile_photos(message.from_user.id)
        if photos.total_count == 0:
            return "❌ Ошибка: У вас нет фото профиля. Бот работает только с реальными аккаунтами."
        
        if not message.from_user.username:
            return "❌ Ошибка: У вас не установлен @username в настройках Telegram."
    except Exception:
        return "⚠️ Ошибка проверки аккаунта."
    return None

# --- ФУНКЦИЯ ФОНОВОЙ ОЧИСТКИ ЗАДАНИЙ ---
async def auto_delete_tasks():
    while True:
        try:
            db.delete_expired_tasks()
        except:
            pass
        await asyncio.sleep(600) # Проверка каждые 10 минут

# --- ОБРАБОТКА КОМАНДЫ /START ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    try:
        # 1. Анти-фрод (Проверка аватара/юзернейма)
        bad_msg = await is_bad_user(message)
        if bad_msg:
            return await message.answer(bad_msg)
        
        user_id = message.from_user.id
        existing_user = db.get_user(user_id)
        
        # 2. Логика реферала (только если юзер НОВЫЙ)
        ref_id = None
        if not existing_user and command.args and command.args.isdigit():
            if int(command.args) != user_id:
                ref_id = int(command.args)
        
        # Регистрация в базе данных
        db.add_user(user_id, ref_id)
        
        # 3. Проверка обязательной подписки (ОП)
        is_subscribed = await check_main_subs(user_id)
        
        if not is_subscribed:
            channels_str = "\n".join(config.REQUIRED_CHANNELS)
            return await message.answer(
                f"❌ **Для работы с ботом подпишись на каналы:**\n\n{channels_str}\n\n"
                f"После подписки снова нажми /start",
                parse_mode="Markdown"
            )

        # 4. НАЧИСЛЕНИЕ ЗА РЕФЕРАЛА (Только после подписки!)
        user_data = db.get_user(user_id)
        # Проверяем 7-ю колонку (ref_bonus_given), индекс [6]
        if user_data and len(user_data) > 6:
            bonus_already_given = user_data[6]
            
            if not bonus_already_given:
                actual_ref_id = user_data[2] # Кто пригласил
                
                if actual_ref_id:
                    # Начисляем Папе (L1) - 5 звезд
                    db.update_balance(actual_ref_id, 5.0)
                    
                    # Ищем Дедушку (L2) - 1 звезда
                    parent_data = db.get_user(actual_ref_id)
                    if parent_data and len(parent_data) > 2 and parent_data[2]:
                        db.update_balance(parent_data[2], 1.0)
                    
                    # Уведомляем пригласившего
                    try:
                        await bot.send_message(
                            actual_ref_id, 
                            "👥 **Новый активный реферал!**\n💰 Начислено: **5.0 ⭐**", 
                            parse_mode="Markdown"
                        )
                    except: pass
                
                # Помечаем, что бонус за этого юзера выдан (больше не платим)
                db.mark_bonus_given(user_id)

        # 5. Главное меню
        await message.answer(
            f"✅ **Доступ разрешен!**\n\nДобро пожаловать в Money Farm. Выполняй задания и зарабатывай звезды!", 
            reply_markup=kb.main_menu(), 
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"Ошибка в /start: {e}")
        await message.answer("⚠️ Ошибка при запуске. Попробуй позже.")

# --- ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ---
@dp.callback_query(F.data == "profile")
async def profile(call: types.CallbackQuery):
    if not await check_main_subs(call.from_user.id):
        return await call.answer("❌ Сначала подпишись на каналы!", show_alert=True)
        
    user = db.get_user(call.from_user.id) 
    # Индекс [1] — это баланс в таблице users
    balance = user[1] if user else 0
    
    # Конвертация для красоты (курс из твоего конфига)
    usd_val = round(balance * 0.015, 2)
    
    text = (
        f"👤 **ПРОФИЛЬ**\n\n"
        f"💰 Баланс: **{balance} ⭐**\n"
        f"💵 Примерно: **{usd_val}$**\n"
    )
    
    # Если баланс позволяет вывести — показываем методы вывода
    if balance >= config.MIN_WITHDRAW:
        await call.message.edit_text(text + "\n✅ Вывод доступен!", reply_markup=kb.withdraw_currency_kb())
    else:
        # Если мало — просто профиль с кнопкой главного меню
        await call.message.edit_text(
            text + f"\n❌ Минимум для вывода: **{config.MIN_WITHDRAW} ⭐**", 
            reply_markup=kb.main_menu(),
            parse_mode="Markdown"
        )

# --- СПИСОК ЗАДАНИЙ ---
@dp.callback_query(F.data == "tasks_list")
async def show_tasks(call: types.CallbackQuery):
    if not await check_main_subs(call.from_user.id): 
        return await call.answer("❌ Сначала подпишись на ОП!", show_alert=True)
    
    tasks = db.get_all_tasks()
    keyboard = []
    
    for t in tasks:
        # t[0] - ID задания, t[1] - Название, t[3] - Награда
        # Показываем только те, что юзер еще НЕ выполнил
        if not db.is_task_completed(call.from_user.id, t[0]):
            keyboard.append([types.InlineKeyboardButton(
                text=f"🎯 {t[1]} (+{t[3]} ⭐)", 
                callback_data=f"view_task_{t[0]}"
            )])
    
    keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")])
    
    if not keyboard or len(keyboard) == 1:
        await call.message.edit_text("📭 Пока нет новых заданий. Заходи позже!", reply_markup=kb.main_menu())
    else:
        await call.message.edit_text("🎯 **Доступные задания:**", 
                                     reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard),
                                     parse_mode="Markdown")

# --- РЕФЕРАЛЬНЫЙ РАЗДЕЛ ---
@dp.callback_query(F.data == "refs")
async def show_refs(call: types.CallbackQuery):
    # Берем количество рефов L1 и L2 из базы
    l1, l2 = db.get_detailed_refs(call.from_user.id)
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={call.from_user.id}"
    
    text = (
        f"👥 **ВАША КОМАНДА**\n\n"
        f"🥇 **Уровень 1:** **{l1}** чел. (+5.0 ⭐)\n"
        f"🥈 **Уровень 2:** **{l2}** чел. (+1.0 ⭐)\n\n"
        f"🔗 **Твоя ссылка для приглашения:**\n"
        f"`{link}`"
    )
    await call.message.edit_text(text, reply_markup=kb.main_menu(), parse_mode="Markdown")

# --- ПРОСМОТР КОНКРЕТНОГО ЗАДАНИЯ ---
@dp.callback_query(F.data.startswith("view_task_"))
async def view_task(call: types.CallbackQuery):
    task_id = int(call.data.split("_")[2])
    # Ищем задачу в базе по ID
    task = next((t for t in db.get_all_tasks() if t[0] == task_id), None)
    
    if task:
        # task[1]-Название, task[3]-Награда, task[2]-Ссылка
        text = (
            f"📢 **ЗАДАНИЕ:** {task[1]}\n"
            f"💰 **НАГРАДА:** {task[3]} ⭐\n\n"
            f"1️⃣ Перейди по ссылке и подпишись.\n"
            f"2️⃣ Вернись и нажми кнопку 'Проверить'."
        )
        await call.message.edit_text(
            text, 
            reply_markup=kb.task_button(task[2], task[0]), # Кнопка-ссылка + кнопка проверки
            parse_mode="Markdown"
        )
    else:
        await call.answer("⚠️ Задание не найдено или уже удалено.", show_alert=True)

# --- ПРОВЕРКА ВЫПОЛНЕНИЯ (Кнопка 'Проверить') ---
@dp.callback_query(F.data.startswith("check_"))
async def check_sub_task(call: types.CallbackQuery):
    task_id = int(call.data.split("_")[1])
    user_id = call.from_user.id

    # 1. Защита: не выполнял ли уже?
    if db.is_task_completed(user_id, task_id):
        return await call.answer("🚫 Награда уже получена!", show_alert=True)

    task = next((t for t in db.get_all_tasks() if t[0] == task_id), None)
    if not task:
        return await call.answer("⚠️ Задание больше не активно.", show_alert=True)
    
    try:
        # Проверяем подписку (в task[4] должен лежать @username или ID канала)
        member = await bot.get_chat_member(chat_id=task[4], user_id=user_id)
        
        if member.status in ["member", "administrator", "creator"]:
            reward = task[3]
            
            # 2. НАЧИСЛЯЕМ ИСПОЛНИТЕЛЮ
            db.update_balance(user_id, reward)
            db.complete_task(user_id, task_id)
            
            # 3. РЕФЕРАЛЬНЫЕ (L1 - 10%, L2 - 5%)
            user_data = db.get_user(user_id)
            parent_id = user_data[2] if user_data else None
            
            if parent_id:
                # Начисляем Папе (10%)
                reward_l1 = round(reward * 0.10, 2)
                db.update_balance(parent_id, reward_l1)
                
                # Ищем Дедушку (5%)
                parent_data = db.get_user(parent_id)
                grandpa_id = parent_data[2] if parent_data and len(parent_data) > 2 else None
                if grandpa_id:
                    reward_l2 = round(reward * 0.05, 2)
                    db.update_balance(grandpa_id, reward_l2)
            
            await call.answer("✅ Подписка подтверждена! Награда начислена.", show_alert=True)
            # Возвращаем юзера в список оставшихся заданий
            await show_tasks(call)
            
        else:
            await call.answer("❌ Ты не подписался на канал!", show_alert=True)
            
    except Exception as e:
        print(f"Ошибка проверки подписки: {e}")
        await call.answer("⚠️ Бот не видит твою подписку. Убедись, что бот - админ в том канале!", show_alert=True)

# --- ЕЖЕДНЕВНЫЙ БОНУС (ЧЕК-ИН) ---
@dp.callback_query(F.data == "daily_bonus")
async def daily_checkin(call: types.CallbackQuery):
    user = db.get_user(call.from_user.id) # [id, balance, ref_id, last_checkin, streak...]
    if not user: return
    
    last_checkin = user[3]
    streak = user[4] or 0
    now = datetime.now()

    # Проверка: прошло ли 24 часа?
    if last_checkin and (now - last_checkin) < timedelta(days=1):
        remaining = (last_checkin + timedelta(days=1)) - now
        hours = remaining.seconds // 3600
        mins = (remaining.seconds // 60) % 60
        return await call.answer(f"⏳ Приходи через {hours}ч. {mins}мин.", show_alert=True)

    # Если пропустил больше 2 дней — сброс серии, иначе +1 (макс до 10 дней)
    new_streak = streak + 1 if (not last_checkin or (now - last_checkin) <= timedelta(days=2)) and streak < 10 else 1
    
    reward = round(new_streak * 0.1, 1) # Награда растет: 0.1, 0.2 ... 1.0 ⭐
    db.update_balance(call.from_user.id, reward)
    db.update_checkin(call.from_user.id, new_streak)
    
    await call.message.answer(f"✅ **День {new_streak}**\n💰 Получено: **{reward} ⭐**", 
                              reply_markup=kb.main_menu(), parse_mode="Markdown")
    await call.answer()

# --- ВЫВОД: ВЫБОР МЕТОДА (Начало FSM) ---
@dp.callback_query(F.data.startswith("meth_"))
async def choose_withdraw_method(call: types.CallbackQuery, state: FSMContext):
    # Если юзер был в режиме промокода — отменяем его
    promo_cache.pop(call.from_user.id, None)
    
    method = call.data.split("_")[1].upper()
    
    # Сохраняем метод в FSM (состояние бота)
    await state.update_data(withdraw_method=method)
    
    # ПЕРЕКЛЮЧАЕМ ЮЗЕРА В СОСТОЯНИЕ ОЖИДАНИЯ СУММЫ
    await state.set_state(WithdrawState.wait_amount)
    
    await call.message.answer(
        f"💎 Выбран метод: **{method}**\n\n"
        f"**Шаг 1:** Введите количество ⭐ для вывода\n"
        f"(Минимум: {config.MIN_WITHDRAW} ⭐)",
        parse_mode="Markdown"
    )
    await call.answer()

# --- 1. ОБРАБОТКА ВВОДА СУММЫ ---
@dp.message(WithdrawState.wait_amount)
async def withdraw_amount_input(message: types.Message, state: FSMContext):
    # Проверяем, что введено число
    if not message.text or not message.text.isdigit():
        return await message.answer("❌ Пожалуйста, введите сумму цифрами (например: 250)")

    amount = int(message.text)
    user_id = message.from_user.id
    user_data = db.get_user(user_id)
    current_balance = user_data[1] if user_data else 0

    # Проверка лимитов
    if amount < config.MIN_WITHDRAW:
        return await message.answer(f"❌ Минимальная сумма вывода: **{config.MIN_WITHDRAW} ⭐**", parse_mode="Markdown")
    
    if amount > current_balance:
        return await message.answer(f"❌ Недостаточно средств! Ваш баланс: **{current_balance} ⭐**", parse_mode="Markdown")

    # Сохраняем сумму в память FSM
    await state.update_data(withdraw_amount=amount)
    
    # Получаем метод, который выбрали на прошлом шаге
    data = await state.get_data()
    method = data.get("withdraw_method")

    # ЛОГИКА РАЗДЕЛЕНИЯ: Звезды vs Остальное
    if method == "STARS":
        await message.answer(
            f"🌟 Вывод: **{amount} Stars**\n\n"
            f"**Шаг 2:** Введите ваш **@username** или ссылку на профиль, куда отправить звёзды.",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            f"💎 Вывод: **{amount} {method}**\n\n"
            f"**Шаг 2:** Введите адрес вашего **кошелька** для получения выплаты.",
            parse_mode="Markdown"
        )
    
    # Переходим к ожиданию реквизитов
    await state.set_state(WithdrawState.wait_details)

# --- 2. ОБРАБОТКА РЕКВИЗИТОВ И СПИСАНИЕ ---
@dp.message(WithdrawState.wait_details)
async def withdraw_details_input(message: types.Message, state: FSMContext):
    details = message.text
    user_id = message.from_user.id
    
    # Забираем данные из памяти FSM
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    method = data.get("withdraw_method")

    # --- КРИТИЧЕСКИЙ МОМЕНТ: СПИСАНИЕ СРЕДСТВ ---
    # Еще раз проверяем баланс перед списанием (на всякий случай)
    user_current = db.get_user(user_id)
    if not user_current or user_current[1] < amount:
        await state.clear()
        return await message.answer("❌ Ошибка: Недостаточно средств на балансе.")

    # Списываем баланс в базе (отрицательное число)
    db.update_balance(user_id, -float(amount))
    
    # Создаем заявку в базе (чтобы админ ее видел)
    db.add_withdraw_request(user_id, amount, method, details)

    # Уведомляем админа
    try:
        admin_text = (
            f"💰 **НОВАЯ ЗАЯВКА НА ВЫВОД**\n\n"
            f"👤 От: `{user_id}`\n"
            f"💵 Сумма: **{amount} ⭐**\n"
            f"🏦 Метод: **{method}**\n"
            f"📝 Реквизиты: `{details}`"
        )
        await bot.send_message(config.ADMIN_ID, admin_text, parse_mode="Markdown")
    except: pass

    await message.answer(
        f"✅ **Заявка принята!**\n\n"
        f"Сумма **{amount} ⭐** списана с вашего баланса.\n"
        f"Ожидайте выплату в течение 24 часов.",
        reply_markup=kb.main_menu(),
        parse_mode="Markdown"
    )
    
    # ПОЛНОСТЬЮ ОЧИЩАЕМ СОСТОЯНИЕ (Выходим из режима вывода)
    await state.clear()

# --- ОБРАБОТКА РЕШЕНИЙ АДМИНА ПО ВЫПЛАТАМ (Авто-возврат) ---
@dp.callback_query(F.data.startswith("adm_"), F.from_user.id == config.ADMIN_ID)
async def admin_decision(call: types.CallbackQuery):
    parts = call.data.split("_")
    # Формат: adm_pay_USERID_AMOUNT или adm_refuse_USERID_AMOUNT
    action = parts[1]
    target_id = int(parts[2])
    amount = float(parts[3])

    if action == "pay":
        try:
            await bot.send_message(target_id, f"✅ **Выплата одобрена!**\nСумма **{amount} ⭐** успешно отправлена на ваши реквизиты.", parse_mode="Markdown")
        except: pass
        await call.message.edit_text(call.message.text + "\n\n✅ **СТАТУС: ВЫПЛАЧЕНО**")
        
    elif action == "refuse":
        # АВТО-ВОЗВРАТ СРЕДСТВ ПРИ ОТКЛОНЕНИИ
        db.update_balance(target_id, amount)
        try:
            await bot.send_message(target_id, f"❌ **Вывод отклонен.**\nСумма **{amount} ⭐** возвращена на ваш баланс.", parse_mode="Markdown")
        except: pass
        await call.message.edit_text(call.message.text + "\n\n❌ **СТАТУС: ОТКЛОНЕНО (Средства возвращены)**")
    
    await call.answer()

# --- АДМИН-КОМАНДЫ (УПРАВЛЕНИЕ) ---

@dp.message(F.text == "/admin", F.from_user.id == config.ADMIN_ID)
async def admin_panel(message: types.Message):
    stats = db.get_admin_stats() # Должна возвращать словарь с ключами: users_count, total_balance, tasks_count, pending_withdraws
    text = (
        f"🖥 **АДМИН-ПАНЕЛЬ**\n\n"
        f"👥 Юзеров: `{stats['users_count']}`\n"
        f"💰 Звезд в системе: `{round(stats['total_balance'], 2)}` ⭐\n"
        f"⏳ Заявок на вывод: `{stats['pending_withdraws']}`\n"
    )
    kb_admin = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📋 Задания", callback_data="adm_tasks_list")],
        [types.InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast")]
    ])
    await message.answer(text, reply_markup=kb_admin, parse_mode="Markdown")

@dp.message(F.text.startswith("/add "), F.from_user.id == config.ADMIN_ID)
async def admin_add_task(message: types.Message):
    try:
        # Формат: /add Название Ссылка Награда @канал Часы
        parts = message.text.split(" ")
        title, url, reward, channel_id, hours = parts[1], parts[2], float(parts[3]), parts[4], int(parts[5])
        expire_time = datetime.now() + timedelta(hours=hours)
        db.add_task(title, url, reward, channel_id, expire_time)
        await message.answer(f"✅ Задание **{title}** добавлено на {hours}ч.!", parse_mode="Markdown")
    except:
        await message.answer("❌ Формат: `/add Имя Ссылка Награда @channel 24`", parse_mode="Markdown")

@dp.message(F.text.startswith("/give "), F.from_user.id == config.ADMIN_ID)
async def admin_give(message: types.Message):
    try:
        parts = message.text.split(" ")
        target, amount = int(parts[1]), float(parts[2])
        db.update_balance(target, amount)
        await message.answer(f"🎁 Начислено {amount} ⭐ пользователю `{target}`")
        try: await bot.send_message(target, f"🎁 Админ начислил вам бонус: **{amount} ⭐**!", parse_mode="Markdown")
        except: pass
    except:
        await message.answer("❌ Формат: `/give ID сумма`")

@dp.message(Command("send"), F.from_user.id == config.ADMIN_ID)
async def admin_broadcast(message: types.Message, command: CommandObject):
    if not command.args: return await message.answer("❌ Напиши текст рассылки после команды.")
    users = db.get_all_users()
    count = 0
    msg = await message.answer("🚀 Начинаю рассылку...")
    for user in users:
        try:
            await bot.send_message(user[0], command.args)
            count += 1
            await asyncio.sleep(0.05)
        except: continue
    await msg.edit_text(f"✅ Рассылка завершена! Получили: {count} чел.")


# --- ОБРАБОТКА ТЕКСТА (ПРОМОКОДЫ) ---
@dp.message(F.text, StateFilter(None)) # Работает только когда юзер НЕ в процессе вывода
async def handle_promo(message: types.Message):
    # Если это не команда, проверяем как промокод
    if message.text.startswith('/'): return
    
    promo_code = message.text.strip()
    user_id = message.from_user.id
    
    # Ищем промокод в базе
    promo = db.get_promo(promo_code)
    
    if not promo:
        # Если это не промокод и не команда, просто игнорим или даем подсказку
        return 

    # promo[0]-ID, [1]-Код, [2]-Сумма, [3]-Макс_активаций, [4]-Использовано
    promo_id, code, reward, max_uses, current_uses = promo
    
    if current_uses >= max_uses:
        return await message.answer("❌ Этот промокод уже закончился!")
    
    if db.is_promo_used(user_id, promo_id):
        return await message.answer("❌ Вы уже активировали этот промокод!")
    
    # Активация
    db.use_promo(user_id, promo_id, reward)
    await message.answer(f"🎁 Промокод активирован!\n💰 Начислено: **{reward} ⭐**", parse_mode="Markdown")

# --- ФУНКЦИЯ ЗАПУСКА ---
async def main():
    # Запускаем Flask для Render (Keep Alive)
    keep_alive()
    
    # Запускаем фоновую задачу очистки старых заданий
    asyncio.create_task(auto_delete_tasks())
    
    print("🚀 Бот Money Farm запущен!")
    
    # Удаляем вебхуки и начинаем опрос серверов Telegram
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
