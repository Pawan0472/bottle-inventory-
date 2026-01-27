from flask import Flask, render_template, request, redirect, url_for, session, send_file
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime
import pandas as pd
import io

app = Flask(__name__)
app.secret_key = "very_secret_key_change_later"

# ---------------- DATABASE ----------------

def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "inventory.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------- LOGIN REQUIRED DECORATOR ----------------

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

# ---------------- LOGIN SYSTEM ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect("/dashboard")
        else:
            error = "Invalid username or password"

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------------- ROOT ----------------

@app.route("/")
def root():
    return redirect("/dashboard")

# ---------------- DASHBOARD ----------------

@app.route("/dashboard")
@login_required()
def dashboard():
    conn = get_db_connection()

    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    total_suppliers = conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]

    today = datetime.now().strftime("%Y-%m-%d")

    today_production = conn.execute(
        "SELECT IFNULL(SUM(quantity_produced), 0) FROM production WHERE date = ?",
        (today,)
    ).fetchone()[0]

    today_sales = conn.execute(
        "SELECT IFNULL(SUM(quantity), 0) FROM sales WHERE date = ?",
        (today,)
    ).fetchone()[0]

    total_finished_stock = conn.execute(
        "SELECT IFNULL(SUM(current_stock), 0) FROM product_stock"
    ).fetchone()[0]

    total_sales_value = conn.execute(
        "SELECT IFNULL(SUM(quantity), 0) FROM sales"
    ).fetchone()[0]

    total_purchase_value = conn.execute(
        "SELECT IFNULL(SUM(quantity * rate), 0) FROM purchase"
    ).fetchone()[0]

    # 🔹 VERY IMPORTANT: SEND EMPTY LISTS FOR CHARTS
    sales_dates = []
    sales_qty = []
    prod_names = []
    prod_qty = []
    cust_names = []
    cust_qty = []
    supp_names = []
    supp_qty = []

    conn.close()

    return render_template(
        "dashboard.html",
        total_products=total_products,
        total_customers=total_customers,
        total_suppliers=total_suppliers,
        today_production=today_production,
        today_sales=today_sales,
        total_finished_stock=total_finished_stock,
        total_sales_value=total_sales_value,
        total_purchase_value=total_purchase_value,

        # charts (empty safe defaults)
        sales_dates=sales_dates,
        sales_qty=sales_qty,
        prod_names=prod_names,
        prod_qty=prod_qty,
        cust_names=cust_names,
        cust_qty=cust_qty,
        supp_names=supp_names,
        supp_qty=supp_qty
    )


# ---------------- PRODUCTS ----------------

UPLOAD_FOLDER = "static/uploads/products"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/products", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def products():
    conn = get_db_connection()

    if request.method == "POST":
        name = request.form["name"]
        volume = request.form["volume"]
        preform_weight = request.form["preform_weight"]
        cap_type = request.form["cap_type"]

        image_file = request.files["image"]
        image_path = None
        if image_file and image_file.filename:
            filename = secure_filename(image_file.filename)
            path = os.path.join(UPLOAD_FOLDER, filename)
            image_file.save(path)
            image_path = path

        conn.execute("""
            INSERT INTO products (name, volume, preform_weight, cap_type, image_path)
            VALUES (?, ?, ?, ?, ?)
        """, (name, volume, preform_weight, cap_type, image_path))

        conn.commit()

    products = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    return render_template("products.html", products=products)

# ---------------- RAW MATERIALS ----------------

@app.route("/raw-materials", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def raw_materials():
    conn = get_db_connection()

    if request.method == "POST":
        name = request.form["name"]
        material_type = request.form["material_type"]
        unit = request.form["unit"]
        current_stock = float(request.form["current_stock"])

        conn.execute("""
            INSERT INTO raw_materials (name, material_type, unit, current_stock)
            VALUES (?, ?, ?, ?)
        """, (name, material_type, unit, current_stock))

        conn.commit()

    materials = conn.execute("SELECT * FROM raw_materials").fetchall()
    conn.close()
    return render_template("raw_materials.html", materials=materials)

# ---------------- BOM ----------------

@app.route("/bom", methods=["GET", "POST"])
@login_required(role="admin")
def bom():
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM products").fetchall()
    materials = conn.execute("SELECT * FROM raw_materials").fetchall()

    if request.method == "POST":
        product_id = request.form["product_id"]
        raw_material_id = request.form["raw_material_id"]
        consumption = float(request.form["consumption_per_unit"])

        conn.execute("""
            INSERT INTO bom (product_id, raw_material_id, consumption_per_unit)
            VALUES (?, ?, ?)
        """, (product_id, raw_material_id, consumption))

        conn.commit()

    bom_list = conn.execute("""
        SELECT bom.id, products.name AS product_name,
               raw_materials.name AS material_name,
               raw_materials.unit,
               bom.consumption_per_unit
        FROM bom
        LEFT JOIN products ON bom.product_id = products.id
        LEFT JOIN raw_materials ON bom.raw_material_id = raw_materials.id
    """).fetchall()

    conn.close()
    return render_template("bom.html", products=products, materials=materials, bom_list=bom_list)

# ---------------- PRODUCTION ----------------

@app.route("/production", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def production():
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM products").fetchall()
    error = None

    if request.method == "POST":
        date = request.form["date"]
        product_id = request.form["product_id"]
        quantity = int(request.form["quantity_produced"])
        rejects = int(request.form["rejects"])
        remarks = request.form["remarks"]

        bom_items = conn.execute("""
            SELECT bom.raw_material_id, bom.consumption_per_unit, raw_materials.current_stock
            FROM bom
            LEFT JOIN raw_materials ON bom.raw_material_id = raw_materials.id
            WHERE bom.product_id = ?
        """, (product_id,)).fetchall()

        if not bom_items:
            error = "No BOM defined for this product!"
        else:
            for item in bom_items:
                required = quantity * float(item["consumption_per_unit"])
                if item["current_stock"] < required:
                    error = "Not enough raw material stock!"
                    break

        if not error:
            conn.execute("""
                INSERT INTO production (date, product_id, quantity_produced, rejects, remarks)
                VALUES (?, ?, ?, ?, ?)
            """, (date, product_id, quantity, rejects, remarks))

            current = conn.execute(
                "SELECT current_stock FROM product_stock WHERE product_id = ?",
                (product_id,)
            ).fetchone()

            if current:
                conn.execute(
                    "UPDATE product_stock SET current_stock = ? WHERE product_id = ?",
                    (current["current_stock"] + quantity, product_id)
                )
            else:
                conn.execute(
                    "INSERT INTO product_stock (product_id, current_stock) VALUES (?, ?)",
                    (product_id, quantity)
                )

            for item in bom_items:
                required = quantity * float(item["consumption_per_unit"])
                new_stock = item["current_stock"] - required
                conn.execute(
                    "UPDATE raw_materials SET current_stock = ? WHERE id = ?",
                    (new_stock, item["raw_material_id"])
                )

            conn.commit()

    production_list = conn.execute("""
        SELECT production.*, products.name AS product_name
        FROM production
        LEFT JOIN products ON production.product_id = products.id
        ORDER BY production.id DESC
    """).fetchall()

    conn.close()
    return render_template("production.html", products=products, production_list=production_list, error=error)

# ---------------- PURCHASE ----------------

@app.route("/purchase", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def purchase():
    conn = get_db_connection()
    suppliers = conn.execute("SELECT * FROM suppliers").fetchall()
    raw_materials = conn.execute("SELECT * FROM raw_materials").fetchall()

    if request.method == "POST":
        date = request.form["date"]
        supplier_id = request.form["supplier_id"]
        raw_material_id = request.form["raw_material_id"]
        quantity = float(request.form["quantity"])
        rate = float(request.form["rate"])
        bill_number = request.form["bill_number"]
        remarks = request.form["remarks"]

        conn.execute("""
            INSERT INTO purchase (date, supplier_id, raw_material_id, quantity, rate, bill_number, remarks)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (date, supplier_id, raw_material_id, quantity, rate, bill_number, remarks))

        current = conn.execute(
            "SELECT current_stock FROM raw_materials WHERE id = ?",
            (raw_material_id,)
        ).fetchone()

        conn.execute(
            "UPDATE raw_materials SET current_stock = ? WHERE id = ?",
            (current["current_stock"] + quantity, raw_material_id)
        )

        conn.commit()

    purchase_list = conn.execute("""
        SELECT purchase.*, suppliers.name AS supplier_name, raw_materials.name AS material_name
        FROM purchase
        LEFT JOIN suppliers ON purchase.supplier_id = suppliers.id
        LEFT JOIN raw_materials ON purchase.raw_material_id = raw_materials.id
        ORDER BY purchase.id DESC
    """).fetchall()

    conn.close()
    return render_template("purchase.html", suppliers=suppliers, raw_materials=raw_materials, purchase_list=purchase_list)

# ---------------- SALES ----------------

@app.route("/sales", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def sales():
    conn = get_db_connection()
    customers = conn.execute("SELECT * FROM customers").fetchall()
    products = conn.execute("SELECT * FROM products").fetchall()
    error = None

    if request.method == "POST":
        date = request.form["date"]
        customer_id = request.form["customer_id"]
        product_id = request.form["product_id"]
        quantity = int(request.form["quantity"])
        dispatch_type = request.form["dispatch_type"]
        vehicle_number = request.form["vehicle_number"]
        remarks = request.form["remarks"]

        current = conn.execute(
            "SELECT current_stock FROM product_stock WHERE product_id = ?",
            (product_id,)
        ).fetchone()

        if not current or current["current_stock"] < quantity:
            error = "Not enough finished stock!"
        else:
            conn.execute("""
                INSERT INTO sales (date, customer_id, product_id, quantity, dispatch_type, vehicle_number, remarks)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (date, customer_id, product_id, quantity, dispatch_type, vehicle_number, remarks))

            conn.execute(
                "UPDATE product_stock SET current_stock = ? WHERE product_id = ?",
                (current["current_stock"] - quantity, product_id)
            )

            conn.commit()

    sales_list = conn.execute("""
        SELECT sales.*, customers.name AS customer_name, products.name
        FROM sales
        LEFT JOIN customers ON sales.customer_id = customers.id
        LEFT JOIN products ON sales.product_id = products.id
        ORDER BY sales.id DESC
    """).fetchall()

    conn.close()
    return render_template("sales.html", customers=customers, products=products, sales=sales_list, error=error)

# ---------------- STOCK ----------------

@app.route("/stock")
@login_required()
def stock():
    conn = get_db_connection()
    stock_list = conn.execute("""
        SELECT products.name, product_stock.current_stock
        FROM product_stock
        LEFT JOIN products ON product_stock.product_id = products.id
    """).fetchall()
    conn.close()
    return render_template("stock.html", stock_list=stock_list)

# ---------------- CUSTOMERS ----------------

@app.route("/customers", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def customers():
    conn = get_db_connection()

    if request.method == "POST":
        name = request.form["name"]
        phone = request.form["phone"]
        address = request.form["address"]

        conn.execute("""
            INSERT INTO customers (name, phone, address)
            VALUES (?, ?, ?)
        """, (name, phone, address))

        conn.commit()

    customers = conn.execute("SELECT * FROM customers").fetchall()
    conn.close()
    return render_template("customers.html", customers=customers)

# ---------------- SUPPLIERS ----------------

@app.route("/suppliers", methods=["GET", "POST"])
@login_required(role=["admin", "data_entry"])
def suppliers():
    conn = get_db_connection()

    if request.method == "POST":
        name = request.form["name"]
        phone = request.form["phone"]
        address = request.form["address"]

        conn.execute("""
            INSERT INTO suppliers (name, phone, address)
            VALUES (?, ?, ?)
        """, (name, phone, address))

        conn.commit()

    suppliers = conn.execute("SELECT * FROM suppliers").fetchall()
    conn.close()
    return render_template("suppliers.html", suppliers=suppliers)

# ---------------- USER MANAGEMENT ----------------

@app.route("/users", methods=["GET", "POST"])
@login_required(role="admin")
def users():
    conn = get_db_connection()
    error = None

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        role = request.form["role"]

        hashed = generate_password_hash(password)

        try:
            conn.execute("""
                INSERT INTO users (username, password, role, is_active)
                VALUES (?, ?, ?, 1)
            """, (username, hashed, role))
            conn.commit()
        except:
            error = "Username already exists"

    users = conn.execute("""
        SELECT id, username, role, is_active
        FROM users
        ORDER BY id
    """).fetchall()

    conn.close()
    return render_template("users.html", users=users, error=error)

@app.route("/users/delete/<int:user_id>")
@login_required(role="admin")
def delete_user(user_id):
    if user_id == session.get("user_id"):
        return "You cannot delete your own account", 400

    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return redirect("/users")

@app.route("/users/reset_password/<int:user_id>", methods=["POST"])
@login_required(role="admin")
def reset_user_password(user_id):
    new_password = request.form["new_password"]

    conn = get_db_connection()
    hashed = generate_password_hash(new_password)

    conn.execute(
        "UPDATE users SET password = ? WHERE id = ?",
        (hashed, user_id)
    )

    conn.commit()
    conn.close()
    return redirect("/users")

# ---------------- REPORTS ----------------

@app.route("/reports")
@login_required()
def reports():
    return render_template("reports.html")

@app.route("/reports/stock")
@login_required()
def stock_report():
    conn = get_db_connection()
    stock_list = conn.execute("""
        SELECT products.name, product_stock.current_stock
        FROM product_stock
        LEFT JOIN products ON product_stock.product_id = products.id
    """).fetchall()
    conn.close()
    return render_template("report_stock.html", stock_list=stock_list)

@app.route("/reports/stock/export")
@login_required()
def export_stock_excel():
    conn = get_db_connection()
    stock_list = conn.execute("""
        SELECT products.name, product_stock.current_stock
        FROM product_stock
        LEFT JOIN products ON product_stock.product_id = products.id
    """).fetchall()
    conn.close()

    df = pd.DataFrame(stock_list, columns=["Product", "Current Stock"])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)

    output.seek(0)
    return send_file(output, as_attachment=True, download_name="stock_report.xlsx")

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(debug=True)
