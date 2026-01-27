import sqlite3

conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE sales ADD COLUMN customer_id INTEGER;")
    print("Added customer_id to sales table")
except Exception as e:
    print("sales.customer_id:", e)

try:
    cursor.execute("ALTER TABLE purchase ADD COLUMN supplier_id INTEGER;")
    print("Added supplier_id to purchase table")
except Exception as e:
    print("purchase.supplier_id:", e)

conn.commit()
conn.close()

print("Done.")
