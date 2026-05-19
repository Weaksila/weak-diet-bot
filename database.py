import sqlite3
import datetime

DB_PATH = "bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            full_name TEXT,
            username TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value INTEGER
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('free_limit', 3)")
    
    columns_to_add = [
        "is_premium BOOLEAN DEFAULT 0",
        "daily_usage INTEGER DEFAULT 0",
        "last_usage_date TEXT",
        "height INTEGER DEFAULT 0",
        "weight INTEGER DEFAULT 0",
        "goal TEXT DEFAULT ''",
        "lang TEXT DEFAULT 'uz'",
        "premium_expire_date TEXT"
    ]
    for col in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
            
    conn.commit()
    conn.close()

def add_user(user_id, full_name, username):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (user_id, full_name, username) VALUES (?, ?, ?)",
                       (user_id, full_name, username))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def get_free_limit():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'free_limit'")
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else 3

def set_free_limit(limit):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = 'free_limit'", (limit,))
    conn.commit()
    conn.close()

def is_premium(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT is_premium, premium_expire_date FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if not result:
        return False
    is_prem, expire_date = result
    if is_prem:
        if expire_date:
            today = datetime.date.today().isoformat()
            if today <= expire_date:
                return True
            else:
                revoke_premium(user_id) # expired
                return False
        return True
    return False

def check_and_update_limit(user_id):
    today = datetime.date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if is_premium(user_id):
        conn.close()
        return True
        
    cursor.execute("SELECT daily_usage, last_usage_date FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return False
        
    daily_usage, last_usage_date = result
    
    free_limit = get_free_limit()
    
    if last_usage_date != today:
        cursor.execute("UPDATE users SET daily_usage = 1, last_usage_date = ? WHERE user_id = ?", (today, user_id))
        conn.commit()
        conn.close()
        return free_limit > 0
    
    if daily_usage < free_limit: 
        cursor.execute("UPDATE users SET daily_usage = daily_usage + 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
        
    conn.close()
    return False

def make_premium(user_id, days=30):
    expire_date = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_premium = 1, premium_expire_date = ? WHERE user_id = ?", (expire_date, user_id))
    conn.commit()
    conn.close()

def revoke_premium(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_premium = 0, premium_expire_date = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_premium_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, full_name, username, premium_expire_date FROM users WHERE is_premium = 1 ORDER BY id DESC")
    users = cursor.fetchall()
    conn.close()
    return users

def get_users_count():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_all_user_ids():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_recent_users(limit=20):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, full_name, username FROM users ORDER BY id DESC LIMIT ?", (limit,))
    users = cursor.fetchall()
    conn.close()
    return users

def update_profile(user_id, height, weight, goal):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET height=?, weight=?, goal=? WHERE user_id=?", (height, weight, goal, user_id))
    conn.commit()
    conn.close()

def get_profile(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT height, weight, goal FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def update_lang(user_id, lang):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, user_id))
    conn.commit()
    conn.close()

def get_lang(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT lang FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 'uz'
