from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash

# 🔥 Paste your Supabase Postgres URL here
DATABASE_URL = "postgresql://postgres.emuskdnhedzecbjnnrzt:Pawan729266kumar@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

def init_db():
    with engine.begin() as conn:

        # ---------------- USERS ----------------
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE
        );
        """))

        # ---------------- PRODUCTS ----------------
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            volume TEXT,
            preform_weight NUMERIC DEFAULT 0,
            cap_type TEXT,
            image_path TEXT
        );
        """))

        # ---------------- RAW MATERIALS ----------------
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS raw_materials (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            material_type TEXT NOT NULL,
            unit TEXT NOT NULL,
            current_stock NUMERIC DEFAULT 0
        );
        """))

        # ---------------- BOM ----------------
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bom (
            id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            raw_material_id INTEGER REFERENCES raw_materials(id) ON DELETE CASCADE,
            consumption_per_unit NUMERIC NOT NULL
        );
        """))

        # ---------------- PRODUCTION ----------------
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS production (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            product_id INTEGER REFERENCES products(id),
            quantity_produced INTEGER NOT NULL,
            rejects INTEGER DEFAULT 0,
            remarks TEXT
        );
        """))

        # ---------------- PRODUCT STOCK ----------------
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS product_stock (
            id SERIAL PRIMARY KEY,
            product_id INTEGER UNIQUE REFERENCES products(id) ON DELETE CASCADE,
            current_stock INTEGER DEFAULT 0
        );
        """))

        # ---------------- CUSTOMERS ----------------
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS customers (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT
        );
        """))

        # ---------------- SUPPLIERS ----------------
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT
        );
        """))

        # ---------------- SALES ----------------
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sales (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            customer_id INTEGER REFERENCES customers(id),
            product_id INTEGER REFERENCES products(id),
            quantity INTEGER NOT NULL,
            dispatch_type TEXT,
            vehicle_number TEXT,
            remarks TEXT
        );
        """))

        # ---------------- PURCHASE ----------------
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS purchase (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            supplier_id INTEGER REFERENCES suppliers(id),
            raw_material_id INTEGER REFERENCES raw_materials(id),
            quantity NUMERIC NOT NULL,
            rate NUMERIC DEFAULT 0,
            bill_number TEXT,
            remarks TEXT
        );
        """))

        # ---------------- CREATE DEFAULT ADMIN (IF NOT EXISTS) ----------------
        admin = conn.execute(text("""
            SELECT id FROM users WHERE username = 'admin'
        """)).fetchone()

        if not admin:
            hashed = generate_password_hash("admin123")
            conn.execute(text("""
                INSERT INTO users (username, password, role, is_active)
                VALUES (:u, :p, :r, TRUE)
            """), {"u": "admin", "p": hashed, "r": "admin"})

            print("✅ Default admin created: admin / admin123")
        else:
            print("ℹ️ Admin already exists, skipped.")

    print("✅ All tables created successfully in Supabase!")

if __name__ == "__main__":
    init_db()
