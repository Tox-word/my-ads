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
        
        # 1. Таблица пользователей
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
        
# 3. Таблица выполненных заданий (теперь task_id — это TEXT)
        cur.execute('''CREATE TABLE IF NOT EXISTS completed_tasks 
                       (user_id BIGINT, 
                        task_id TEXT, 
                        PRIMARY KEY (user_id, task_id))''')

        # 4. Таблица заявок на вывод
        cur.execute('''CREATE TABLE IF NOT EXISTS withdrawals 
                       (id SERIAL PRIMARY KEY, 
                        user_id BIGINT, 
                        amount REAL, 
                        method TEXT, 
                        address TEXT, 
                        status TEXT DEFAULT 'pending')''')
        
        # 5. Таблица промокодов
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
        return True  # Пользователь успешно добавлен (НОВЫЙ)
    return False     # Пользователь уже существует (СТАРЫЙ)

# Начисление с защитой от минуса
def update_balance(user_id, amount):
    with get_connection() as conn:
        cur = conn.cursor()
        # Если amount отрицательный (вывод), проверяем, хватает ли баланса
        if amount < 0:
            cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s AND balance >= %s", (amount, user_id, abs(amount)))
        else:
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

def delete_task(task_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        conn.commit()

def delete_expired_tasks():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tasks WHERE expires_at < %s", (datetime.now(),))
        conn.commit()

# --- ФУНКЦИИ ВЫВОДА ---

def create_withdrawal(user_id, amount, method, address):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO withdrawals (user_id, amount, method, address) VALUES (%s, %s, %s, %s)", 
                    (user_id, amount, method, address))
        conn.commit()

# --- ЧЕК-ИНЫ, ПРОМО И СТАТИСТИКА ---

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

# Считаем оба уровня рефералов
def get_detailed_refs(user_id):
    with get_connection() as conn:
        cur = conn.cursor()
        # Уровень 1
        cur.execute("SELECT COUNT(*) FROM users WHERE ref_id = %s", (user_id,))
        l1 = cur.fetchone()[0]
        # Уровень 2
        cur.execute("SELECT COUNT(*) FROM users WHERE ref_id IN (SELECT id FROM users WHERE ref_id = %s)", (user_id,))
        l2 = cur.fetchone()[0]
        return l1, l2

def get_admin_stats():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        u_count = cur.fetchone()[0]
        cur.execute("SELECT SUM(balance) FROM users")
        total_bal = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM tasks")
        t_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'pending'")
        w_count = cur.fetchone()[0]
        
        return {
            'users_count': u_count,
            'total_balance': total_bal,
            'tasks_count': t_count,
            'pending_withdraws': w_count
        }

def get_all_users():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users")
        return cur.fetchall()




# Универсальная проверка: выполнено ли задание или активирован ли промокод
def check_task_completed(user_id, task_id):
    with get_connection() as conn:
        cur = conn.cursor()
        # Приводим task_id к строке на случай, если пришло число
        cur.execute("SELECT 1 FROM completed_tasks WHERE user_id = %s AND task_id = %s", (user_id, str(task_id)))
        return cur.fetchone() is not None

# Запись о выполнении (и для обычных задач, и для промо)
def add_completed_task(user_id, task_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO completed_tasks (user_id, task_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, str(task_id)))
        conn.commit()

# Исправленная функция: название совпадает с вызовом в main.py
def add_promo_to_db(code, reward, uses, chan_id=None):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO promos (code, reward, uses_left, required_channel_id) 
            VALUES (%s, %s, %s, %s) 
            ON CONFLICT (code) 
            DO UPDATE SET uses_left = EXCLUDED.uses_left, reward = EXCLUDED.reward
        """, (code.upper(), reward, uses, chan_id))
        conn.commit()
