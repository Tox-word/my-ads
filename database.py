import psycopg2
from psycopg2.extras import DictCursor
import os
from datetime import datetime

# Берем URL базы из переменных окружения Render
DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    # sslmode='require' обязателен для работы с базой на Render
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    """Создает все таблицы с нуля. Если таблица есть — не трогает её."""
    with get_connection() as conn:
        cur = conn.cursor()
        
        # 1. ТАБЛИЦА ПОЛЬЗОВАТЕЛЕЙ
        # Добавил сразу все нужные тебе поля, чтобы индексы не плыли
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            balance REAL DEFAULT 0,
            ref_id BIGINT,
            last_checkin TIMESTAMP,
            checkin_streak INTEGER DEFAULT 0,
            total_ref_earned REAL DEFAULT 0,
            ref_bonus_given BOOLEAN DEFAULT FALSE
        )''')

        # 2. ТАБЛИЦА ВЫПОЛНЕННЫХ ДЕЙСТВИЙ (Задания + Промо)
        # Это «черный список», чтобы нельзя было юзать промо или задание дважды
        cur.execute('''CREATE TABLE IF NOT EXISTS completed_actions (
            user_id BIGINT,
            action_id TEXT, 
            PRIMARY KEY (user_id, action_id)
        )''')
        
        conn.commit()
        print("✅ База данных успешно инициализирована")

def get_user(user_id):
    """Получаем данные юзера в виде словаря (dict), чтобы не путать индексы."""
    with get_connection() as conn:
        # DictCursor позволяет писать user['balance'] вместо user[1]
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()

def add_user(user_id, ref_id=None):
    """Добавляет юзера, если его еще нет."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (id, ref_id) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (user_id, ref_id))
        conn.commit()

def update_balance(user_id, amount):
    """Универсальное изменение баланса (и плюс, и минус)."""
    with get_connection() as conn:
        cur = conn.cursor()
        # Округляем до 2 знаков, чтобы не было 0.0000001
        cur.execute("UPDATE users SET balance = ROUND((balance + %s)::numeric, 2) WHERE id = %s", (float(amount), user_id))
        conn.commit()

# --- ЛОГИКА РЕФЕРАЛОВ (L1 и L2) ---
def give_ref_reward(new_user_id):
    """Выплачивает бонусы 'Папе' (5.0) и 'Дедушке' (1.0)."""
    user = get_user(new_user_id)
    if not user or user['ref_bonus_given']:
        return False # Уже давали бонус или юзера нет

    parent_id = user['ref_id']
    if parent_id:
        # 1. Платим Папе (L1)
        update_balance(parent_id, 5.0)
        
        # Ищем Дедушку (L2)
        parent_user = get_user(parent_id)
        if parent_user and parent_user['ref_id']:
            update_balance(parent_user['ref_id'], 1.0)
            
        # Помечаем, что за этого юзера бонусы выплачены
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET ref_bonus_given = TRUE WHERE id = %s", (new_user_id,))
            conn.commit()
        return True
    return False

# --- ЛОГИКА ПРОМОКОДОВ (БЕЗОПАСНАЯ) ---
def check_promo(code):
    """Ищет промокод в базе."""
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT * FROM promos WHERE UPPER(code) = %s", (code.upper(),))
        return cur.fetchone()

def use_promo_safe(user_id, code, reward):
    """Активирует промокод с защитой от повторов."""
    action_id = f"PROMO_{code.upper()}"
    
    with get_connection() as conn:
        cur = conn.cursor()
        # Проверяем, не вводил ли юзер ЭТОТ промокод раньше
        cur.execute("SELECT 1 FROM completed_actions WHERE user_id = %s AND action_id = %s", (user_id, action_id))
        if cur.fetchone():
            return "USED" # Уже было
            
        # Если всё ок — уменьшаем кол-во юзов у промокода и даем деньги
        cur.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE UPPER(code) = %s AND uses_left > 0", (code.upper(),))
        if cur.rowcount > 0:
            update_balance(user_id, reward)
            cur.execute("INSERT INTO completed_actions (user_id, action_id) VALUES (%s, %s)", (user_id, action_id))
            conn.commit()
            return "SUCCESS"
        return "EXPIRED" # Кончились попытки

# --- ЗАДАНИЯ ---
def complete_task_db(user_id, task_id, reward):
    """Помечает задание как выполненное и начисляет награду."""
    action_id = f"TASK_{task_id}"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO completed_actions (user_id, action_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, action_id))
        if cur.rowcount > 0:
            update_balance(user_id, reward)
            conn.commit()
            return True
        return False


def clear_database_full():
    """Полная зачистка и пересоздание таблиц."""
    with get_connection() as conn:
        cur = conn.cursor()
        # Удаляем все таблицы, которые мы создавали
        cur.execute('''DROP TABLE IF EXISTS users, tasks, completed_actions, promos, withdrawals CASCADE;''')
        conn.commit()
    # После удаления сразу вызываем инициализацию, чтобы бот не вылетел
    init_db()
