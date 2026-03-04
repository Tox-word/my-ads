import sqlite3
from datetime import datetime

def init_db():
    with sqlite3.connect("bot.db") as conn:
        cur = conn.cursor()
        
        # 1. Таблица пользователей
        cur.execute('''CREATE TABLE IF NOT EXISTS users 
                       (id INTEGER PRIMARY KEY, 
                        balance REAL DEFAULT 0, 
                        ref_id INTEGER)''')
        
        # 2. Таблица заданий (унифицированная версия)
        cur.execute('''CREATE TABLE IF NOT EXISTS tasks 
                       (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        title TEXT, 
                        url TEXT, 
                        reward REAL, 
                        chat_id TEXT,
                        expires_at DATETIME)''')
        
        # 3. Таблица выполненных заданий
        cur.execute('''CREATE TABLE IF NOT EXISTS completed_tasks 
                       (user_id INTEGER, 
                        task_id INTEGER, 
                        PRIMARY KEY (user_id, task_id))''')

        # 4. Таблица заявок на вывод
        cur.execute('''CREATE TABLE IF NOT EXISTS withdrawals 
                       (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        user_id INTEGER, 
                        amount REAL, 
                        method TEXT, 
                        address TEXT, 
                        status TEXT DEFAULT 'pending')''')
        conn.commit()

# --- ФУНКЦИИ ПОЛЬЗОВАТЕЛЕЙ ---

def get_user(user_id):
    with sqlite3.connect("bot.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return cur.fetchone()

def add_user(user_id, ref_id=None):
    if not get_user(user_id):
        with sqlite3.connect("bot.db") as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (id, ref_id) VALUES (?, ?)", (user_id, ref_id))
            conn.commit()

def update_balance(user_id, amount):
    with sqlite3.connect("bot.db") as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (round(amount, 2), user_id))
        conn.commit()

# --- ФУНКЦИИ ЗАДАНИЙ ---

def add_task(title, url, reward, chat_id, expire_time):
    with sqlite3.connect("bot.db") as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO tasks (title, url, reward, chat_id, expires_at) VALUES (?, ?, ?, ?, ?)", 
                    (title, url, reward, chat_id, expire_time))
        conn.commit()

def get_all_tasks():
    with sqlite3.connect("bot.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tasks")
        return cur.fetchall()

def is_task_completed(user_id, task_id):
    with sqlite3.connect("bot.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_id = ?", (user_id, task_id))
        return cur.fetchone() is not None

def complete_task(user_id, task_id):
    with sqlite3.connect("bot.db") as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO completed_tasks (user_id, task_id) VALUES (?, ?)", (user_id, task_id))
        conn.commit()

def delete_task(task_id):
    with sqlite3.connect("bot.db") as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()

def delete_expired_tasks():
    with sqlite3.connect("bot.db") as conn:
        # Автоматическое удаление заданий, время которых истекло
        conn.execute("DELETE FROM tasks WHERE expires_at < ?", (datetime.now(),))
        conn.commit()

# --- ФУНКЦИИ ВЫВОДА ---

def create_withdrawal(user_id, amount, method, address):
    with sqlite3.connect("bot.db") as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO withdrawals (user_id, amount, method, address) VALUES (?, ?, ?, ?)", 
                    (user_id, amount, method, address))
        conn.commit()
        return cur.lastrowid
