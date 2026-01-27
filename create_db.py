import sqlite3

conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

# Products table
cursor.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    volume TEXT,
    preform_weight REAL,
    cap_type TEXT,
    image_path TEXT
)
""")

# Sales table (basic version, we will expand)
cursor.execute("""
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    customer_name TEXT,
    product_id INTEGER,
    quantity INTEGER,
    packing_image_path TEXT,
    lr_copy_path TEXT,
    dispatch_type TEXT,
    vehicle_number TEXT,
    remarks TEXT
)
""")


# Product stock table
cursor.execute("""
CREATE TABLE IF NOT EXISTS product_stock (
    product_id INTEGER PRIMARY KEY,
    current_stock INTEGER DEFAULT 0
)
""")


# Production table
cursor.execute("""
CREATE TABLE IF NOT EXISTS production (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    product_id INTEGER,
    quantity_produced INTEGER,
    rejects INTEGER,
    remarks TEXT
)
""")

# Raw materials table
cursor.execute("""
CREATE TABLE IF NOT EXISTS raw_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    material_type TEXT NOT NULL,
    unit TEXT NOT NULL,
    current_stock REAL DEFAULT 0
)
""")

# BOM table (Bill of Materials)
cursor.execute("""
CREATE TABLE IF NOT EXISTS bom (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    raw_material_id INTEGER,
    consumption_per_unit REAL
)
""")

# Purchase table
cursor.execute("""
CREATE TABLE IF NOT EXISTS purchase (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    supplier_name TEXT,
    raw_material_id INTEGER,
    quantity REAL,
    rate REAL,
    bill_number TEXT,
    bill_image_path TEXT,
    remarks TEXT
)
""")


# Customers table
cursor.execute("""
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT
)
""")

# Suppliers table
cursor.execute("""
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT
)
""")

# BOM table
cursor.execute("""
CREATE TABLE IF NOT EXISTS bom (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    raw_material_id INTEGER NOT NULL,
    consumption_per_unit REAL NOT NULL
)
""")




conn.commit()
conn.close()

print("Database and tables created successfully.")
