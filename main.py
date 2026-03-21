import asyncio
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import config as cfg
import database as db
import kb

from flask import Flask
from threading import Thread

# --- СОСТОЯНИЯ (FSM) ---
# Это критически важно для Вывода и Промо, чтобы бот не путал текст
class UserStates(StatesGroup):
    wait_withdraw_amount = State()  # Ждем сумму вывода
    wait_withdraw_wallet = State()  # Ждем кошелек (TON/Stars)
    wait_promo_code = State()       # Ждем ввод промокода (если через кнопку)

# --- KEEP ALIVE (Для работы на Render 24/7) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is Alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=cfg.BOT_TOKEN)
# MemoryStorage нужен, чтобы FSM (состояния) работали
dp = Dispatcher(storage=MemoryStorage())

# --- ОБЩИЕ ПРОВЕРКИ ---
async def check_subs(user_id):
    """Проверка подписки на обязательные каналы."""
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

# --- ОБРАБОТЧИК /START ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    
    # 1. Проверка на "живого" юзера (Фото + Юзернейм)
    photos = await bot.get_user_profile_photos(user_id)
    if photos.total_count == 0 or not message.from_user.username:
        return await message.answer("❌ **Ошибка!** Для работы с ботом необходимо иметь фото профиля и установленный @username.")

    # 2. Реферальная ссылка
    ref_id = None
    if command.args and command.args.isdigit():
        if int(command.args) != user_id:
            ref_id = int(command.args)

    # 3. Добавляем в базу
    db.add_user(user_id, ref_id)
    
    # 4. Проверка подписки
    if not await check_subs(user_id):
        return await message.answer(f"⚠️ Для доступа подпишитесь на каналы:\n{', '.join(cfg.REQUIRED_CHANNELS)}")

    # 5. Начисление бонусов L1 и L2 (только один раз при первом входе)
    if db.give_ref_reward(user_id):
        # Если бонусы выданы, уведомляем "Папу"
        user_data = db.get_user(user_id)
        parent_id = user_data['ref_id']
        try:
            await bot.send_message(parent_id, "💎 **У вас новый активный реферал!**\nНачислено: +5.0 ⭐")
        except: pass

    await message.answer("🏝 **Добро пожаловать на Money Farm!**", reply_markup=kb.main_menu())

# --- АДМИН-КОМАНДЫ ---

# 1. Рассылка: /send Текст
@dp.message(Command("send"))
async def admin_broadcast(message: types.Message):
    if message.from_user.id != cfg.ADMIN_ID: return
    
    text = message.text.replace("/send", "").strip()
    if not text: return await message.answer("Введите текст после команды.")
    
    users = db.get_all_users() # Нужно добавить эту функцию в database.py (просто SELECT id FROM users)
    count = 0
    for user in users:
        try:
            await bot.send_message(user[0], text)
            count += 1
            await asyncio.sleep(0.05) # Защита от спам-фильтра ТГ
        except: continue
    await message.answer(f"✅ Рассылка завершена! Получили: {count} чел.")

# 2. Добавить промо: /addpromo КОД НАГРАДА КОЛ-ВО
@dp.message(Command("addpromo"))
async def admin_add_promo(message: types.Message, command: CommandObject):
    if message.from_user.id != cfg.ADMIN_ID: return
    
    try:
        args = command.args.split()
        code, reward, uses = args[0].upper(), float(args[1]), int(args[2])
        
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO promos (code, reward, uses_left) VALUES (%s, %s, %s)", (code, reward, uses))
            conn.commit()
        await message.answer(f"✅ Промокод `{code}` на {reward} ⭐ создан ({uses} шт.)")
    except:
        await message.answer("❌ Ошибка! Формат: `/addpromo GIFT 50 100`")

# 3. Изменить баланс: /setbal ID СУММА
@dp.message(Command("setbal"))
async def admin_set_bal(message: types.Message, command: CommandObject):
    if message.from_user.id != cfg.ADMIN_ID: return
    try:
        args = command.args.split()
        target_id, amount = int(args[0]), float(args[1])
        db.update_balance(target_id, amount)
        await message.answer(f"✅ Баланс юзера `{target_id}` изменен на {amount}")
    except:
        await message.answer("❌ Ошибка! Формат: `/setbal 123456 500`")


# --- ПРОФИЛЬ И РЕФЕРАЛЫ ---
@dp.callback_query(F.data == "profile")
async def cb_profile(call: types.CallbackQuery):
    user = db.get_user(call.from_user.id)
    text = (f"👤 **Ваш профиль:**\n\n"
            f"💰 Баланс: `{user['balance']}` ⭐\n"
            f"👥 Рефералов: `{user['total_ref_earned']}`\n" # Здесь можно добавить счетчик кол-ва
            f"🆔 Ваш ID: `{call.from_user.id}`")
    await call.message.edit_text(text, reply_markup=kb.main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "refs")
async def cb_refs(call: types.CallbackQuery):
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start={call.from_user.id}"
    text = (f"👥 **Реферальная программа:**\n\n"
            f"1️⃣ Уровень (Папа): **5.0 ⭐**\n"
            f"2️⃣ Уровень (Дедушка): **1.0 ⭐**\n\n"
            f"🔗 Ваша ссылка:\n`{ref_link}`")
    await call.message.edit_text(text, reply_markup=kb.main_menu(), parse_mode="Markdown")

# --- ЛОГИКА ПРОМОКОДОВ ---
@dp.callback_query(F.data == "use_promo")
async def cb_promo_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("⌨️ Введите промокод:")
    await state.set_state(UserStates.wait_promo_code)

@dp.message(UserStates.wait_promo_code)
async def process_promo(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    result = db.use_promo_safe(message.from_user.id, code, 0) # Награда берется из базы внутри функции
    
    if result == "SUCCESS":
        await message.answer("✅ Промокод активирован!")
    elif result == "USED":
        await message.answer("❌ Вы уже использовали этот код.")
    else:
        await message.answer("❌ Код неверный или закончился.")
    await state.clear()

# --- ЛОГИКА ВЫВОДА (ТОН / STARS) ---
@dp.callback_query(F.data == "withdraw")
async def cb_withdraw_start(call: types.CallbackQuery, state: FSMContext):
    user = db.get_user(call.from_user.id)
    if user['balance'] < 500: # Твой порог вывода
        return await call.answer("❌ Минимум для вывода: 500 ⭐", show_alert=True)
    
    await call.message.answer("💰 Введите сумму для вывода:")
    await state.set_state(UserStates.wait_withdraw_amount)

@dp.message(UserStates.wait_withdraw_amount)
async def process_withdraw_amt(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("🔢 Введите число!")
    
    amount = int(message.text)
    user = db.get_user(message.from_user.id)
    
    if amount > user['balance'] or amount < 500:
        return await message.answer("❌ Недостаточно средств или сумма меньше минимума.")
    
    await state.update_data(withdraw_amount=amount)
    await message.answer("💎 Введите ваш адрес (TON кошелек или ID для Stars):")
    await state.set_state(UserStates.wait_withdraw_wallet)

@dp.message(UserStates.wait_withdraw_wallet)
async def process_withdraw_end(message: types.Message, state: FSMContext):
    data = await state.get_data()
    amount = data['withdraw_amount']
    wallet = message.text
    
    # 1. Снимаем баланс
    db.update_balance(message.from_user.id, -amount)
    
    # 2. Уведомляем админа
    admin_text = (f"🔔 **Заявка на вывод!**\n\n"
                  f"👤 Юзер: `{message.from_user.id}`\n"
                  f"💰 Сумма: `{amount}` ⭐\n"
                  f"👛 Кошелек: `{wallet}`")
    await bot.send_message(cfg.ADMIN_ID, admin_text, parse_mode="Markdown")
    
    await message.answer("✅ Заявка отправлена! Ожидайте выплаты.")
    await state.clear()

# --- ЕДИНЫЙ ЗАПУСК (ТОЛЬКО ОДИН В ФАЙЛЕ!) ---
async def main():
    # Запускаем базу
    db.init_db()
    
    # Запускаем фоновый веб-сервер для Render
    keep_alive()
    
    print("🚀 Бот Money Farm запущен и готов к работе!")
    
    # Удаляем вебхуки и начинаем опрос
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
