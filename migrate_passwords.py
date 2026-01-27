import sqlite3
from werkzeug.security import generate_password_hash

conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

users = cursor.execute("SELECT id, password FROM users").fetchall()

for u in users:
    user_id = u[0]
    old_password = u[1]

    # If already hashed, skip
    if old_password.startswith("pbkdf2"):
        continue

    hashed = generate_password_hash(old_password)

    cursor.execute(
        "UPDATE users SET password = ? WHERE id = ?",
        (hashed, user_id)
    )

print("All existing passwords converted to hashed format.")

conn.commit()
conn.close()
