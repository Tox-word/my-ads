import psycopg2
import os
from datetime import datetime

# Берем URL из Environment Variables на Render
DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    with get_connection() as conn:
        cur = conn.cursor()
        
        # 1. Таблица пользователей (Добавлены поля для чек-инов и статистики рефов)
        cur.execute('''CREATE TABLE IF NOT EXISTS users 
                       (id BIGINT PRIMARY KEY, 
                        balance REAL DEFAULT 0, 
                        ref_id BIGINT,
                        last_checkin TIMESTAMP,
                        checkin_streak INTEGER DEFAULT 0,
                        total_ref_earned REAL DEFAULT 0)''')
        
        # 2. Таблица заданий
        cur.execute('''CREATE TABLE IF NOT EXISTS tasks 
                       (id SERIAL PRIMARY KEY, 
                        title TEXT, 
                        url TEXT, 
                        reward REAL, 
                        chat_id TEXT,
                        expires_at TIMESTAMP)''')
        
        # 3. Таблица выполненных заданий
        cur.execute('''CREATE TABLE IF NOT EXISTS completed_tasks 
                       (user_id BIGINT, 
                        task_id INTEGER, 
                        PRIMARY KEY (user_id, task_id))''')

        # 4. Таблица заявок на вывод
        cur.execute('''CREATE TABLE IF NOT EXISTS withdrawals 
                       (id SERIAL PRIMARY KEY, 
                        user_id BIGINT, 
                        amount REAL, 
                        method TEXT, 
                        address TEXT, 
                        status TEXT DEFAULT 'pending')''')
        
        # 5. Таблица промокодов (НОВОЕ)
        cur.execute('''CREATE TABLE IF NOT EXISTS promos 
                       (code TEXT PRIMARY KEY, 
                        reward REAL, 
                        uses_left INTEGER,
                        required_channel_id TEXT)''')
        
        conn.commit()

# --- ФУНКЦИИ ПОЛЬЗОВАТЕЛЕЙ ---

def get_user(user_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, balance, ref_id, last_checkin, checkin_streak, total_ref_earned FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()

def add_user(user_id, ref_id=None):
    if not get_user(user_id):
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (id, ref_id) VALUES (%s, %s)", (user_id, ref_id))
            conn.commit()

def update_balance(user_id, amount):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (round(amount, 2), user_id))
        conn.commit()

# --- ФУНКЦИИ ЗАДАНИЙ ---

def add_task(title, url, reward, chat_id, expire_time):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO tasks (title, url, reward, chat_id, expires_at) VALUES (%s, %s, %s, %s, %s)", 
                    (title, url, reward, chat_id, expire_time))
        conn.commit()

def get_all_tasks():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tasks")
        return cur.fetchall()

def is_task_completed(user_id, task_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM completed_tasks WHERE user_id = %s AND task_id = %s", (user_id, task_id))
        return cur.fetchone() is not None

def complete_task(user_id, task_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO completed_tasks (user_id, task_id) VALUES (%s, %s)", (user_id, task_id))
        conn.commit()

# --- ФУНКЦИИ ВЫВОДА ---

def create_withdrawal(user_id, amount, method, address):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO withdrawals (user_id, amount, method, address) VALUES (%s, %s, %s, %s)", 
                    (user_id, amount, method, address))
        conn.commit()
        cur.execute("SELECT LASTVAL()")
        return cur.fetchone()[0]

# --- НОВЫЕ ФУНКЦИИ (ЧЕК-ИНЫ И ПРОМО) ---

def update_checkin(user_id, streak):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_checkin = %s, checkin_streak = %s WHERE id = %s", 
                    (datetime.now(), streak, user_id))
        conn.commit()

def get_promo(code):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM promos WHERE code = %s", (code,))
        return cur.fetchone()

def use_promo(code):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE code = %s", (code,))
        conn.commit()
