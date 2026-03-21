import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

# Берем URL из Environment Variables на Render
DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    # Используем RealDictCursor, чтобы обращаться к данным по именам: user['balance']
    return psycopg2.connect(DATABASE_URL, sslmode='require', cursor_factory=RealDictCursor)

def init_db():
    with get_connection() as conn:
        cur = conn.cursor()
        
        # 1. Пользователи
        cur.execute('''CREATE TABLE IF NOT EXISTS users 
                       (id BIGINT PRIMARY KEY, 
                        balance REAL DEFAULT 0, 
                        ref_id BIGINT,
                        last_checkin TIMESTAMP,
                        checkin_streak INTEGER DEFAULT 0,
                        total_ref_earned REAL DEFAULT 0)''')

        # 2. Задания
        cur.execute('''CREATE TABLE IF NOT EXISTS tasks 
                       (id SERIAL PRIMARY KEY, 
                        title TEXT, 
                        url TEXT, 
                        reward REAL, 
                        chat_id TEXT,
                        expires_at TIMESTAMP)''')
        
        # 3. Выполненные действия (и задания, и промокоды)
        cur.execute('''CREATE TABLE IF NOT EXISTS completed_actions 
                       (user_id BIGINT, 
                        action_id TEXT, 
                        PRIMARY KEY (user_id, action_id))''')

        # 4. Промокоды
        cur.execute('''CREATE TABLE IF NOT EXISTS promos 
                       (code TEXT PRIMARY KEY, 
                        reward REAL, 
                        uses_left INTEGER)''')
        
        conn.commit()

# --- РАБОТА С ПОЛЬЗОВАТЕЛЯМИ ---

def get_user(user_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()

def add_user(user_id, ref_id=None):
    if not get_user(user_id):
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (id, ref_id) VALUES (%s, %s)", (user_id, ref_id))
            conn.commit()
        return True 
    return False

def update_balance(user_id, amount):
    with get_connection() as conn:
        cur = conn.cursor()
        # Универсальное начисление/списание
        cur.execute("UPDATE users SET balance = ROUND((balance + %s)::numeric, 2) WHERE id = %s", (amount, user_id))
        conn.commit()

# --- РАБОТА С ЗАДАНИЯМИ ---

def get_active_tasks():
    with get_connection() as conn:
        cur = conn.cursor()
        # Выбираем только те, что не истекли
        cur.execute("SELECT * FROM tasks WHERE expires_at > %s", (datetime.now(),))
        return cur.fetchall()

def get_task_by_id(task_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        return cur.fetchone()

def is_action_completed(user_id, action_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM completed_actions WHERE user_id = %s AND action_id = %s", (user_id, str(action_id)))
        return cur.fetchone() is not None

def complete_user_task(user_id, task_id, reward):
    if not is_action_completed(user_id, f"task_{task_id}"):
        with get_connection() as conn:
            cur = conn.cursor()
            # Записываем выполнение
            cur.execute("INSERT INTO completed_actions (user_id, action_id) VALUES (%s, %s)", (user_id, f"task_{task_id}"))
            # Начисляем деньги
            cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (reward, user_id))
            conn.commit()
            return True
    return False

# --- РАБОТА С ПРОМОКОДАМИ ---

def add_promo(code, reward, uses):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO promos (code, reward, uses_left) VALUES (%s, %s, %s) ON CONFLICT (code) DO UPDATE SET uses_left = EXCLUDED.uses_left", 
                    (code.upper(), reward, uses))
        conn.commit()

def get_promo(code):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM promos WHERE code = %s", (code.upper(),))
        return cur.fetchone()

def use_promo_safe(user_id, code):
    promo = get_promo(code)
    if promo and promo['uses_left'] > 0:
        action_id = f"promo_{code.upper()}"
        if not is_action_completed(user_id, action_id):
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE code = %s", (code.upper(),))
                cur.execute("INSERT INTO completed_actions (user_id, action_id) VALUES (%s, %s)", (user_id, action_id))
                conn.commit()
                update_balance(user_id, promo['reward'])
                return "SUCCESS"
        return "USED"
    return "NOT_FOUND"

# --- СТАТИСТИКА И РЕФЕРАЛЫ ---

def get_admin_stats():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count, SUM(balance) as total FROM users")
        u_stats = cur.fetchone()
        cur.execute("SELECT COUNT(*) as count FROM tasks WHERE expires_at > %s", (datetime.now(),))
        t_count = cur.fetchone()['count']
        return {
            'users_count': u_stats['count'],
            'total_balance': u_stats['total'] or 0,
            'tasks_count': t_count
        }

def get_all_users():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users")
        return [row['id'] for row in cur.fetchall()]
