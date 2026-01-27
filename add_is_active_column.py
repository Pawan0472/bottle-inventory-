import sqlite3

conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1;")
    print("is_active column added successfully.")
except Exception as e:
    print("Column already exists or error:", e)

conn.commit()
conn.close()
print("Done.")
