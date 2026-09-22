import sqlite3
import os
import sys

DB_FILE = os.path.join(os.path.dirname(__file__), "users.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS authorized_users (
            email TEXT PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

def add_email(email):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO authorized_users (email) VALUES (?)", (email,))
        conn.commit()
        print(f"✅ Successfully authorized '{email}'. They can now log in.")
    except sqlite3.IntegrityError:
        print(f"⚠️ '{email}' is already authorized.")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    
    if len(sys.argv) > 1:
        email_to_add = sys.argv[1]
    else:
        email_to_add = input("Enter the email address to authorize: ").strip()
        
    if email_to_add and "@" in email_to_add:
        add_email(email_to_add)
    else:
        print("❌ Invalid email address.")
