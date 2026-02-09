from flask import Flask, render_template, request, redirect, session, send_file
import os
from functools import wraps
from datetime import datetime
import io
import pandas as pd

from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, text


# =========================================================
# APP CONFIG
# =========================================================

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change_this_secret_key")

APP_NAME = "SS Packaging Inventory"


# =========================================================
# DATABASE (SUPABASE POSTGRES)
# =========================================================

DATABASE_URL = "postgresql://postgres.emuskdnhedzecbjnnrzt:Ilika20252026@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"

# For local testing only, you can hardcode:
# DATABASE_URL = "PASTE_SUPABASE_URL_HERE"

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL missing. Add it in environment variables.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def get_db_connection():
    return engine.connect()


def fetchone_dict(result):
    row = result.fetchone()
    return dict(row._mapping) if row else None


def fetchall_dict(result):
    rows = result.fetchall()
    return [dict(r._mapping) for r in rows]


# =========================================================
# LOGIN REQUIRED DECORATOR
# =========================================================

def login_required(role=None):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                return redirect("/login")

            if role:
                user_role = session.get("role")

                if isinstance(role, list):
                    if user_role not in role:
                        return "Access Denied", 403
                else:
                    if user_role != role:
                        return "Access Denied", 403

            return f(*args, **kwargs)

        return decorated_function
    return wrapper


# =========================================================
# LOGIN / LOGOUT
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = get_db_connection()

        result = conn.execute(
            text("SELECT * FROM users WHERE username = :u AND is_active = true"),
            {"u": username},
        )
        user = fetchone_dict(result)
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect("/dashboard")

        error = "Invalid username or password"

    return render_template("login.html", error=error, app_name=APP_NAME)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
def root():
    return redirect("/dashboard")


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required()
def dashboard():
    conn = get_db_connection()

    total_products = conn.execute(text("SELECT COUNT(*) FROM products")).scalar() or 0
    total_customers = conn.execute(text("SELECT COUNT(*) FROM customers")).scalar() or 0
    total_suppliers = conn.execute(text("SELECT COUNT(*) FROM suppliers")).scalar() or 0

    today = datetime.now().strftime("%Y-%m-%d")

    today_production = conn.execute(
        text("SELECT COALESCE(SUM(quantity_produced),0) FROM production WHERE date = :d"),
        {"d": today},
    ).scalar() or 0

    today_sales = conn.execute(
        text("SELECT COALESCE(SUM(quantity),0) FROM sales WHERE date = :d"),
        {"d": today},
    ).scalar() or 0

    total_finished_stock = conn.execute(
        text("SELECT COALESCE(SUM(current_stock),0) FROM product_stock")
    ).scalar() or 0

    total_sales_value = conn.execute(
        text("SELECT COALESCE(SUM(quantity),0) FROM sales")
    ).scalar() or 0

    total_purchase_value = conn.execute(
        text("SELECT COALESCE(SUM(quantity * rate),0) FROM purchase")
    ).scalar() or 0

    # --- Sales Trend
    sales_trend_rows = conn.execute(text("""
        SELECT date, COALESCE(SUM(quantity),0) AS total_qty
        FROM sales
        GROUP BY date
        ORDER BY date DESC
        LIMIT 7
    """)).fetchall()

    sales_trend_rows = list(reversed(sales_trend_rows))
    sales_dates = [str(r[0]) for r in sales_trend_rows]
    sales_qty = [int(r[1]) for r in sales_trend_rows]

    # --- Production by product
    prod_rows = conn.execute(text("""
        SELECT p.name, COALESCE(SUM(pr.quantity_produced),0) AS total_qty
        FROM production pr
        LEFT JOIN products p ON pr.product_id = p.id
        GROUP BY p.name
        ORDER BY total_qty DESC
        LIMIT 5
    """)).fetchall()

    prod_names = [r[0] for r in prod_rows]
    prod_qty = [int(r[1]) for r in prod_rows]

    # --- Top customers
    cust_rows = conn.execute(text("""
        SELECT c.name, COALESCE(SUM(s.quantity),0) AS total_qty
        FROM sales s
        LEFT JOIN customers c ON s.customer_id = c.id
        GROUP BY c.name
        ORDER BY total_qty DESC
        LIMIT 5
    """)).fetchall()

    cust_names = [r[0] for r in cust_rows]
    cust_qty = [int(r[1]) for r in cust_rows]

    # --- Top suppliers
    supp_rows = conn.execute(text("""
        SELECT sp.name, COALESCE(SUM(pu.quantity),0) AS total_qty
        FROM purchase pu
        LEFT JOIN suppliers sp ON pu.supplier_id = sp.id
        GROUP BY sp.name
        ORDER BY total_qty DESC
        LIMIT 5
    """)).fetchall()

    supp_names = [r[0] for r in supp_rows]
    supp_qty = [float(r[1]) for r in supp_rows]

    # --- Low raw materials
    low_raw_materials_rows = conn.execute(text("""
        SELECT name, current_stock, unit
        FROM raw_materials
        WHERE current_stock < 50
        ORDER BY current_stock ASC
    """)).fetchall()

    low_raw_materials = [
        {"name": r[0], "current_stock": float(r[1]), "unit": r[2]}
        for r in low_raw_materials_rows
    ]

    # --- Low finished products
    low_finished_rows = conn.execute(text("""
        SELECT p.name, p.volume, ps.current_stock
        FROM product_stock ps
        LEFT JOIN products p ON ps.product_id = p.id
        WHERE ps.current_stock < 1000
        ORDER BY ps.current_stock ASC
    """)).fetchall()

    low_finished_products = [
        {"name": r[0], "volume": r[1], "current_stock": int(r[2])}
        for r in low_finished_rows
    ]

    conn.close()

    return render_template(
        "dashboard.html",
        app_name=APP_NAME,
        total_products=total_products,
        total_customers=total_customers,
        total_suppliers=total_suppliers,
        today_production=today_production,
        today_sales=today_sales,
        total_finished_stock=total_finished_stock,
        total_sales_value=total_sales_value,
        total_purchase_value=total_purchase_value,
        sales_dates=sales_dates,
        sales_qty=sales_qty,
        prod_names=prod_names,
        prod_qty=prod_qty,
        cust_names=cust_names,
        cust_qty=cust_qty,
        supp_names=supp_names,
        supp_qty=supp_qty,
        low_raw_materials=low_raw_materials,
        low_finished_products=low_finished_products
    )


# =========================================================
# PRODUCTS
# =========================================================

@app.route("/products", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def products():
    conn = get_db_connection()

    if request.method == "POST":
        conn.execute(text("""
            INSERT INTO products (name, volume, preform_weight, cap_type)
            VALUES (:n, :v, :pw, :ct)
        """), {
            "n": request.form["name"],
            "v": request.form["volume"],
            "pw": request.form["preform_weight"],
            "ct": request.form["cap_type"]
        })
        conn.commit()

    products_list = fetchall_dict(conn.execute(text("SELECT * FROM products ORDER BY id DESC")))
    conn.close()
    return render_template("products.html", products=products_list, app_name=APP_NAME)


# =========================================================
# RAW MATERIALS
# =========================================================

@app.route("/raw-materials", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def raw_materials():
    conn = get_db_connection()

    if request.method == "POST":
        conn.execute(text("""
            INSERT INTO raw_materials (name, material_type, unit, current_stock)
            VALUES (:n, :t, :u, :s)
        """), {
            "n": request.form["name"],
            "t": request.form["material_type"],
            "u": request.form["unit"],
            "s": request.form["current_stock"]
        })
        conn.commit()

    materials = fetchall_dict(conn.execute(text("SELECT * FROM raw_materials ORDER BY id DESC")))
    conn.close()
    return render_template("raw_materials.html", materials=materials, app_name=APP_NAME)


# =========================================================
# BOM
# =========================================================

@app.route("/bom", methods=["GET", "POST"])
@login_required(role="admin")
def bom():
    conn = get_db_connection()

    products_list = fetchall_dict(conn.execute(text("SELECT * FROM products ORDER BY name")))
    materials_list = fetchall_dict(conn.execute(text("SELECT * FROM raw_materials ORDER BY name")))

    if request.method == "POST":
        conn.execute(text("""
            INSERT INTO bom (product_id, raw_material_id, consumption_per_unit)
            VALUES (:p, :r, :c)
        """), {
            "p": request.form["product_id"],
            "r": request.form["raw_material_id"],
            "c": request.form["consumption_per_unit"]
        })
        conn.commit()

    bom_list = fetchall_dict(conn.execute(text("""
        SELECT bom.id,
               p.name AS product_name,
               p.volume AS volume,
               rm.name AS material_name,
               rm.unit AS unit,
               bom.consumption_per_unit
        FROM bom
        LEFT JOIN products p ON bom.product_id = p.id
        LEFT JOIN raw_materials rm ON bom.raw_material_id = rm.id
        ORDER BY bom.id DESC
    """)))

    conn.close()
    return render_template("bom.html",
                           products=products_list,
                           materials=materials_list,
                           bom_list=bom_list,
                           app_name=APP_NAME)


# =========================================================
# PRODUCTION (BOM LOGIC)
# =========================================================

@app.route("/production", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def production():
    conn = get_db_connection()

    products_list = fetchall_dict(conn.execute(text("SELECT * FROM products ORDER BY name")))
    error = None

    if request.method == "POST":
        date = request.form["date"]
        product_id = int(request.form["product_id"])
        qty = int(request.form["quantity_produced"])
        rejects = int(request.form["rejects"] or 0)
        remarks = request.form["remarks"]

        bom_items = fetchall_dict(conn.execute(text("""
            SELECT bom.raw_material_id,
                   bom.consumption_per_unit,
                   rm.current_stock
            FROM bom
            LEFT JOIN raw_materials rm ON bom.raw_material_id = rm.id
            WHERE bom.product_id = :pid
        """), {"pid": product_id}))

        if not bom_items:
            error = "No BOM defined for this product!"
        else:
            # Check stock
            for item in bom_items:
                required = qty * float(item["consumption_per_unit"])
                if float(item["current_stock"]) < required:
                    error = f"Not enough raw material stock!"
                    break

        if not error:
            # Insert production
            conn.execute(text("""
                INSERT INTO production (date, product_id, quantity_produced, rejects, remarks)
                VALUES (:d, :pid, :q, :r, :rm)
            """), {"d": date, "pid": product_id, "q": qty, "r": rejects, "rm": remarks})

            # Increase finished stock
            current = conn.execute(text("""
                SELECT current_stock FROM product_stock WHERE product_id = :pid
            """), {"pid": product_id}).fetchone()

            if current:
                conn.execute(text("""
                    UPDATE product_stock
                    SET current_stock = current_stock + :q
                    WHERE product_id = :pid
                """), {"q": qty, "pid": product_id})
            else:
                conn.execute(text("""
                    INSERT INTO product_stock (product_id, current_stock)
                    VALUES (:pid, :q)
                """), {"pid": product_id, "q": qty})

            # Reduce raw materials
            for item in bom_items:
                required = qty * float(item["consumption_per_unit"])
                conn.execute(text("""
                    UPDATE raw_materials
                    SET current_stock = current_stock - :req
                    WHERE id = :rid
                """), {"req": required, "rid": item["raw_material_id"]})

            conn.commit()

    production_list = fetchall_dict(conn.execute(text("""
        SELECT pr.*, p.name AS product_name, p.volume
        FROM production pr
        LEFT JOIN products p ON pr.product_id = p.id
        ORDER BY pr.id DESC
    """)))

    conn.close()
    return render_template("production.html",
                           products=products_list,
                           production_list=production_list,
                           error=error,
                           app_name=APP_NAME)


# =========================================================
# PURCHASE
# =========================================================

@app.route("/purchase", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def purchase():
    conn = get_db_connection()

    suppliers_list = fetchall_dict(conn.execute(text("SELECT * FROM suppliers ORDER BY name")))
    raw_materials_list = fetchall_dict(conn.execute(text("SELECT * FROM raw_materials ORDER BY name")))

    if request.method == "POST":
        conn.execute(text("""
            INSERT INTO purchase (date, supplier_id, raw_material_id, quantity, rate, bill_number, remarks)
            VALUES (:d, :sid, :rid, :q, :r, :bn, :rm)
        """), {
            "d": request.form["date"],
            "sid": request.form["supplier_id"],
            "rid": request.form["raw_material_id"],
            "q": request.form["quantity"],
            "r": request.form["rate"],
            "bn": request.form["bill_number"],
            "rm": request.form["remarks"]
        })

        # Add stock
        conn.execute(text("""
            UPDATE raw_materials
            SET current_stock = current_stock + :q
            WHERE id = :rid
        """), {"q": request.form["quantity"], "rid": request.form["raw_material_id"]})

        conn.commit()

    purchase_list = fetchall_dict(conn.execute(text("""
        SELECT pu.*, sp.name AS supplier_name, rm.name AS material_name, rm.unit
        FROM purchase pu
        LEFT JOIN suppliers sp ON pu.supplier_id = sp.id
        LEFT JOIN raw_materials rm ON pu.raw_material_id = rm.id
        ORDER BY pu.id DESC
    """)))

    conn.close()
    return render_template("purchase.html",
                           suppliers=suppliers_list,
                           raw_materials=raw_materials_list,
                           purchase_list=purchase_list,
                           app_name=APP_NAME)


# =========================================================
# SALES
# =========================================================

@app.route("/sales", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def sales():
    conn = get_db_connection()

    customers_list = fetchall_dict(conn.execute(text("SELECT * FROM customers ORDER BY name")))
    products_list = fetchall_dict(conn.execute(text("SELECT * FROM products ORDER BY name")))

    error = None

    if request.method == "POST":
        date = request.form["date"]
        customer_id = int(request.form["customer_id"])
        product_id = int(request.form["product_id"])
        qty = int(request.form["quantity"])
        dispatch_type = request.form["dispatch_type"]
        vehicle_number = request.form["vehicle_number"]
        remarks = request.form["remarks"]

        current = conn.execute(text("""
            SELECT current_stock FROM product_stock WHERE product_id = :pid
        """), {"pid": product_id}).fetchone()

        if not current or int(current[0]) < qty:
            error = "Not enough finished stock!"
        else:
            conn.execute(text("""
                INSERT INTO sales (date, customer_id, product_id, quantity, dispatch_type, vehicle_number, remarks)
                VALUES (:d, :cid, :pid, :q, :dt, :vn, :rm)
            """), {
                "d": date,
                "cid": customer_id,
                "pid": product_id,
                "q": qty,
                "dt": dispatch_type,
                "vn": vehicle_number,
                "rm": remarks
            })

            conn.execute(text("""
                UPDATE product_stock
                SET current_stock = current_stock - :q
                WHERE product_id = :pid
            """), {"q": qty, "pid": product_id})

            conn.commit()

    sales_list = fetchall_dict(conn.execute(text("""
        SELECT s.*, c.name AS customer_name,
               p.name AS product_name, p.volume
        FROM sales s
        LEFT JOIN customers c ON s.customer_id = c.id
        LEFT JOIN products p ON s.product_id = p.id
        ORDER BY s.id DESC
    """)))

    conn.close()
    return render_template("sales.html",
                           customers=customers_list,
                           products=products_list,
                           sales=sales_list,
                           error=error,
                           app_name=APP_NAME)


# =========================================================
# STOCK
# =========================================================

@app.route("/stock")
@login_required()
def stock():
    conn = get_db_connection()

    stock_list = fetchall_dict(conn.execute(text("""
        SELECT p.name, p.volume, ps.current_stock
        FROM product_stock ps
        LEFT JOIN products p ON ps.product_id = p.id
        ORDER BY p.name
    """)))

    conn.close()
    return render_template("stock.html", stock_list=stock_list, app_name=APP_NAME)


# =========================================================
# CUSTOMERS
# =========================================================

@app.route("/customers", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def customers():
    conn = get_db_connection()

    if request.method == "POST":
        conn.execute(text("""
            INSERT INTO customers (name, phone, address)
            VALUES (:n, :p, :a)
        """), {
            "n": request.form["name"],
            "p": request.form["phone"],
            "a": request.form["address"]
        })
        conn.commit()

    customers_list = fetchall_dict(conn.execute(text("SELECT * FROM customers ORDER BY id DESC")))
    conn.close()
    return render_template("customers.html", customers=customers_list, app_name=APP_NAME)


# =========================================================
# SUPPLIERS
# =========================================================

@app.route("/suppliers", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def suppliers():
    conn = get_db_connection()

    if request.method == "POST":
        conn.execute(text("""
            INSERT INTO suppliers (name, phone, address)
            VALUES (:n, :p, :a)
        """), {
            "n": request.form["name"],
            "p": request.form["phone"],
            "a": request.form["address"]
        })
        conn.commit()

    suppliers_list = fetchall_dict(conn.execute(text("SELECT * FROM suppliers ORDER BY id DESC")))
    conn.close()
    return render_template("suppliers.html", suppliers=suppliers_list, app_name=APP_NAME)


# =========================================================
# USERS (ROLE MANAGEMENT)
# =========================================================

@app.route("/users", methods=["GET", "POST"])
@login_required(role="admin")
def users():
    conn = get_db_connection()
    error = None

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        role = request.form["role"]

        try:
            hashed = generate_password_hash(password)

            conn.execute(text("""
                INSERT INTO users (username, password, role, is_active)
                VALUES (:u, :p, :r, true)
            """), {"u": username, "p": hashed, "r": role})

            conn.commit()
        except:
            error = "Username already exists"

    users_list = fetchall_dict(conn.execute(text("""
        SELECT id, username, role, is_active
        FROM users
        ORDER BY id
    """)))

    conn.close()
    return render_template("users.html", users=users_list, error=error, app_name=APP_NAME)


@app.route("/users/toggle/<int:user_id>")
@login_required(role="admin")
def toggle_user(user_id):
    if user_id == session.get("user_id"):
        return "You cannot disable your own account", 400

    conn = get_db_connection()
    conn.execute(text("""
        UPDATE users
        SET is_active = NOT is_active
        WHERE id = :id
    """), {"id": user_id})
    conn.commit()
    conn.close()
    return redirect("/users")


@app.route("/users/reset_password/<int:user_id>", methods=["POST"])
@login_required(role="admin")
def reset_user_password(user_id):
    new_password = request.form["new_password"].strip()
    hashed = generate_password_hash(new_password)

    conn = get_db_connection()
    conn.execute(text("""
        UPDATE users
        SET password = :p
        WHERE id = :id
    """), {"p": hashed, "id": user_id})
    conn.commit()
    conn.close()
    return redirect("/users")


# =========================================================
# REPORTS + EXPORT
# =========================================================

@app.route("/reports")
@login_required()
def reports():
    return render_template("reports.html", app_name=APP_NAME)


@app.route("/reports/stock")
@login_required()
def report_stock():
    conn = get_db_connection()
    stock_list = fetchall_dict(conn.execute(text("""
        SELECT p.name, p.volume, ps.current_stock
        FROM product_stock ps
        LEFT JOIN products p ON ps.product_id = p.id
        ORDER BY p.name
    """)))
    conn.close()
    return render_template("report_stock.html", stock_list=stock_list, app_name=APP_NAME)


@app.route("/reports/raw-materials")
@login_required()
def report_raw_materials():
    conn = get_db_connection()
    materials = fetchall_dict(conn.execute(text("""
        SELECT * FROM raw_materials ORDER BY name
    """)))
    conn.close()
    return render_template("report_raw_materials.html", materials=materials, app_name=APP_NAME)


@app.route("/reports/production")
@login_required()
def report_production():
    conn = get_db_connection()
    production_list = fetchall_dict(conn.execute(text("""
        SELECT pr.*, p.name AS product_name, p.volume
        FROM production pr
        LEFT JOIN products p ON pr.product_id = p.id
        ORDER BY pr.id DESC
    """)))
    conn.close()
    return render_template("report_production.html", production_list=production_list, app_name=APP_NAME)


@app.route("/reports/sales", methods=["GET", "POST"])
@login_required()
def report_sales():
    conn = get_db_connection()
    sales_list = []

    if request.method == "POST":
        from_date = request.form["from_date"]
        to_date = request.form["to_date"]

        sales_list = fetchall_dict(conn.execute(text("""
            SELECT s.date, c.name AS customer_name,
                   p.name AS product_name, p.volume,
                   s.quantity
            FROM sales s
            LEFT JOIN customers c ON s.customer_id = c.id
            LEFT JOIN products p ON s.product_id = p.id
            WHERE s.date BETWEEN :f AND :t
            ORDER BY s.date
        """), {"f": from_date, "t": to_date}))

    conn.close()
    return render_template("report_sales.html", sales_list=sales_list, app_name=APP_NAME)


@app.route("/reports/purchase", methods=["GET", "POST"])
@login_required()
def report_purchase():
    conn = get_db_connection()
    purchase_list = []

    if request.method == "POST":
        from_date = request.form["from_date"]
        to_date = request.form["to_date"]

        purchase_list = fetchall_dict(conn.execute(text("""
            SELECT pu.date, sp.name AS supplier_name,
                   rm.name AS material_name,
                   pu.quantity, pu.rate
            FROM purchase pu
            LEFT JOIN suppliers sp ON pu.supplier_id = sp.id
            LEFT JOIN raw_materials rm ON pu.raw_material_id = rm.id
            WHERE pu.date BETWEEN :f AND :t
            ORDER BY pu.date
        """), {"f": from_date, "t": to_date}))

    conn.close()
    return render_template("report_purchase.html", purchase_list=purchase_list, app_name=APP_NAME)


# =========================================================
# EXPORT TO EXCEL (Stock)
# =========================================================

@app.route("/reports/stock/export")
@login_required()
def export_stock_excel():
    conn = get_db_connection()
    rows = conn.execute(text("""
        SELECT p.name AS product, p.volume AS volume, ps.current_stock AS stock
        FROM product_stock ps
        LEFT JOIN products p ON ps.product_id = p.id
        ORDER BY p.name
    """)).fetchall()
    conn.close()

    df = pd.DataFrame(rows, columns=["Product", "Volume", "Current Stock"])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)

    output.seek(0)
    return send_file(output, as_attachment=True, download_name="stock_report.xlsx")


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    app.run(debug=True)
