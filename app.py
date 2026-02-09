from flask import Flask, render_template, request, redirect, session, send_file, jsonify
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

# IMPORTANT:
# Do NOT hardcode secret key (GitHub will block)
# Add SECRET_KEY in Vercel Environment Variables
app.secret_key = os.environ.get("SECRET_KEY", "change_this_secret_key")

APP_NAME = "SS Packaging Inventory"


# =========================================================
# DATABASE (SUPABASE POSTGRES)
# =========================================================

# IMPORTANT:
# Do NOT hardcode database url (GitHub will block)
# Add DATABASE_URL in Vercel Environment Variables
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL missing. Add it in Vercel Environment Variables.")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"sslmode": "require"}
)


def fetchone_dict(result):
    row = result.fetchone()
    return dict(row._mapping) if row else None


def fetchall_dict(result):
    rows = result.fetchall()
    return [dict(r._mapping) for r in rows]


# =========================================================
# PERMISSIONS HELPERS
# =========================================================

MODULES = [
    ("dashboard", "Dashboard"),
    ("products", "Products"),
    ("raw_materials", "Raw Materials"),
    ("bom", "BOM"),
    ("production", "Production"),
    ("purchase", "Purchase"),
    ("sales", "Sales"),
    ("stock", "Stock"),
    ("customers", "Customers"),
    ("suppliers", "Suppliers"),
    ("reports", "Reports"),
    ("users", "User Management"),
]


def get_user_permissions(user_id: int):
    """
    Returns dict:
    {
      'can_dashboard': True,
      'can_products': False,
      ...
    }
    """
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT *
            FROM user_permissions
            WHERE user_id = :uid
        """), {"uid": user_id}).fetchone()

        if row:
            return dict(row._mapping)

        # If no permission row exists, create default safe permissions
        # (dashboard + stock only)
        conn.execute(text("""
            INSERT INTO user_permissions (
                user_id,
                can_dashboard,
                can_stock
            ) VALUES (
                :uid,
                true,
                true
            )
        """), {"uid": user_id})

        row2 = conn.execute(text("""
            SELECT *
            FROM user_permissions
            WHERE user_id = :uid
        """), {"uid": user_id}).fetchone()

        return dict(row2._mapping)


def has_permission(module_name: str):
    """
    module_name: dashboard/products/raw_materials...
    """
    user_id = session.get("user_id")
    if not user_id:
        return False

    perms = session.get("permissions")
    if not perms:
        perms = get_user_permissions(user_id)
        session["permissions"] = perms

    key = f"can_{module_name}"
    return bool(perms.get(key, False))


def permission_required(module_name: str):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                return redirect("/login")

            if not has_permission(module_name):
                return render_template(
                    "access_denied.html",
                    app_name=APP_NAME,
                    module_name=module_name
                ), 403

            return f(*args, **kwargs)
        return decorated_function
    return wrapper


# =========================================================
# LOGIN REQUIRED DECORATOR (only login)
# =========================================================

def login_required():
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                return redirect("/login")
            return f(*args, **kwargs)
        return decorated_function
    return wrapper


# =========================================================
# ROOT
# =========================================================

@app.route("/")
def root():
    return redirect("/dashboard")


# =========================================================
# LOGIN / LOGOUT
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        with engine.begin() as conn:
            result = conn.execute(
                text("SELECT * FROM users WHERE username = :u AND is_active = true"),
                {"u": username},
            )
            user = fetchone_dict(result)

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]

            # load permissions
            session["permissions"] = get_user_permissions(user["id"])

            return redirect("/dashboard")

        error = "Invalid username or password"

    return render_template("login.html", error=error, app_name=APP_NAME)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# =========================================================
# GLOBAL TEMPLATE VARIABLES (Sidebar control)
# =========================================================

@app.context_processor
def inject_permissions():
    perms = session.get("permissions", {})
    return dict(
        app_name=APP_NAME,
        permissions=perms,
        username=session.get("username", "")
    )


# =========================================================
# ACCESS DENIED PAGE (simple)
# =========================================================

@app.route("/access-denied")
@login_required()
def access_denied_page():
    return render_template("access_denied.html", app_name=APP_NAME, module_name="")


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
@permission_required("dashboard")
def dashboard():
    with engine.begin() as conn:

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

        total_purchase_value = conn.execute(
            text("SELECT COALESCE(SUM(quantity * rate),0) FROM purchase")
        ).scalar() or 0

    return render_template(
        "dashboard.html",
        total_products=total_products,
        total_customers=total_customers,
        total_suppliers=total_suppliers,
        today_production=today_production,
        today_sales=today_sales,
        total_finished_stock=total_finished_stock,
        total_purchase_value=total_purchase_value,
    )


# =========================================================
# PRODUCTS
# =========================================================

@app.route("/products", methods=["GET", "POST"])
@permission_required("products")
def products():
    with engine.begin() as conn:
        if request.method == "POST":
            name = request.form["name"].strip()

            # duplicate protection
            dup = conn.execute(text("""
                SELECT id FROM products WHERE LOWER(name) = LOWER(:n)
            """), {"n": name}).fetchone()

            if dup:
                return render_template(
                    "products.html",
                    products=fetchall_dict(conn.execute(text("SELECT * FROM products ORDER BY id DESC"))),
                    error="❌ Product name already exists!"
                )

            conn.execute(text("""
                INSERT INTO products (name, volume, preform_weight, cap_type)
                VALUES (:n, :v, :pw, :ct)
            """), {
                "n": name,
                "v": request.form["volume"],
                "pw": float(request.form["preform_weight"] or 0),
                "ct": request.form["cap_type"]
            })

        products_list = fetchall_dict(conn.execute(text("SELECT * FROM products ORDER BY id DESC")))

    return render_template("products.html", products=products_list)


# =========================================================
# RAW MATERIALS
# =========================================================

@app.route("/raw-materials", methods=["GET", "POST"])
@permission_required("raw_materials")
def raw_materials():
    with engine.begin() as conn:
        if request.method == "POST":
            name = request.form["name"].strip()

            # duplicate protection
            dup = conn.execute(text("""
                SELECT id FROM raw_materials WHERE LOWER(name) = LOWER(:n)
            """), {"n": name}).fetchone()

            if dup:
                return render_template(
                    "raw_materials.html",
                    materials=fetchall_dict(conn.execute(text("SELECT * FROM raw_materials ORDER BY id DESC"))),
                    error="❌ Raw material name already exists!"
                )

            conn.execute(text("""
                INSERT INTO raw_materials (name, material_type, unit, current_stock)
                VALUES (:n, :t, :u, :s)
            """), {
                "n": name,
                "t": request.form["material_type"],
                "u": request.form["unit"],
                "s": float(request.form["current_stock"] or 0)
            })

        materials = fetchall_dict(conn.execute(text("SELECT * FROM raw_materials ORDER BY id DESC")))

    return render_template("raw_materials.html", materials=materials)


# =========================================================
# BOM
# =========================================================

@app.route("/bom", methods=["GET", "POST"])
@permission_required("bom")
def bom():
    with engine.begin() as conn:
        products_list = fetchall_dict(conn.execute(text("SELECT * FROM products ORDER BY name")))
        materials_list = fetchall_dict(conn.execute(text("SELECT * FROM raw_materials ORDER BY name")))

        if request.method == "POST":
            conn.execute(text("""
                INSERT INTO bom (product_id, raw_material_id, consumption_per_unit)
                VALUES (:p, :r, :c)
            """), {
                "p": int(request.form["product_id"]),
                "r": int(request.form["raw_material_id"]),
                "c": float(request.form["consumption_per_unit"])
            })

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

    return render_template("bom.html",
                           products=products_list,
                           materials=materials_list,
                           bom_list=bom_list)


# =========================================================
# PRODUCTION
# =========================================================

@app.route("/production", methods=["GET", "POST"])
@permission_required("production")
def production():
    error = None

    with engine.begin() as conn:
        products_list = fetchall_dict(conn.execute(text("SELECT * FROM products ORDER BY name")))

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
                for item in bom_items:
                    required = qty * float(item["consumption_per_unit"])
                    if float(item["current_stock"]) < required:
                        error = "Not enough raw material stock!"
                        break

            if not error:
                conn.execute(text("""
                    INSERT INTO production (date, product_id, quantity_produced, rejects, remarks)
                    VALUES (:d, :pid, :q, :r, :rm)
                """), {"d": date, "pid": product_id, "q": qty, "r": rejects, "rm": remarks})

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

                for item in bom_items:
                    required = qty * float(item["consumption_per_unit"])
                    conn.execute(text("""
                        UPDATE raw_materials
                        SET current_stock = current_stock - :req
                        WHERE id = :rid
                    """), {"req": required, "rid": item["raw_material_id"]})

        production_list = fetchall_dict(conn.execute(text("""
            SELECT pr.*, p.name AS product_name, p.volume
            FROM production pr
            LEFT JOIN products p ON pr.product_id = p.id
            ORDER BY pr.id DESC
        """)))

    return render_template("production.html",
                           products=products_list,
                           production_list=production_list,
                           error=error)


# =========================================================
# PURCHASE
# =========================================================

@app.route("/purchase", methods=["GET", "POST"])
@permission_required("purchase")
def purchase():
    with engine.begin() as conn:
        suppliers_list = fetchall_dict(conn.execute(text("SELECT * FROM suppliers ORDER BY name")))
        raw_materials_list = fetchall_dict(conn.execute(text("SELECT * FROM raw_materials ORDER BY name")))

        if request.method == "POST":
            conn.execute(text("""
                INSERT INTO purchase (date, supplier_id, raw_material_id, quantity, rate, bill_number, remarks)
                VALUES (:d, :sid, :rid, :q, :r, :bn, :rm)
            """), {
                "d": request.form["date"],
                "sid": int(request.form["supplier_id"]),
                "rid": int(request.form["raw_material_id"]),
                "q": float(request.form["quantity"]),
                "r": float(request.form["rate"]),
                "bn": request.form["bill_number"],
                "rm": request.form["remarks"]
            })

            conn.execute(text("""
                UPDATE raw_materials
                SET current_stock = current_stock + :q
                WHERE id = :rid
            """), {"q": float(request.form["quantity"]), "rid": int(request.form["raw_material_id"])})

        purchase_list = fetchall_dict(conn.execute(text("""
            SELECT pu.*, sp.name AS supplier_name, rm.name AS material_name, rm.unit
            FROM purchase pu
            LEFT JOIN suppliers sp ON pu.supplier_id = sp.id
            LEFT JOIN raw_materials rm ON pu.raw_material_id = rm.id
            ORDER BY pu.id DESC
        """)))

    return render_template("purchase.html",
                           suppliers=suppliers_list,
                           raw_materials=raw_materials_list,
                           purchase_list=purchase_list)


# =========================================================
# SALES
# =========================================================

@app.route("/sales", methods=["GET", "POST"])
@permission_required("sales")
def sales():
    error = None

    with engine.begin() as conn:
        customers_list = fetchall_dict(conn.execute(text("SELECT * FROM customers ORDER BY name")))
        products_list = fetchall_dict(conn.execute(text("SELECT * FROM products ORDER BY name")))

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

        sales_list = fetchall_dict(conn.execute(text("""
            SELECT s.*, c.name AS customer_name,
                   p.name AS product_name, p.volume
            FROM sales s
            LEFT JOIN customers c ON s.customer_id = c.id
            LEFT JOIN products p ON s.product_id = p.id
            ORDER BY s.id DESC
        """)))

    return render_template("sales.html",
                           customers=customers_list,
                           products=products_list,
                           sales=sales_list,
                           error=error)


# =========================================================
# STOCK
# =========================================================

@app.route("/stock")
@permission_required("stock")
def stock():
    with engine.begin() as conn:
        stock_list = fetchall_dict(conn.execute(text("""
            SELECT p.name, p.volume, ps.current_stock
            FROM product_stock ps
            LEFT JOIN products p ON ps.product_id = p.id
            ORDER BY p.name
        """)))

    return render_template("stock.html", stock_list=stock_list)


# =========================================================
# CUSTOMERS
# =========================================================

@app.route("/customers", methods=["GET", "POST"])
@permission_required("customers")
def customers():
    with engine.begin() as conn:
        if request.method == "POST":
            name = request.form["name"].strip()

            # duplicate protection
            dup = conn.execute(text("""
                SELECT id FROM customers WHERE LOWER(name) = LOWER(:n)
            """), {"n": name}).fetchone()

            if dup:
                return render_template(
                    "customers.html",
                    customers=fetchall_dict(conn.execute(text("SELECT * FROM customers ORDER BY id DESC"))),
                    error="❌ Customer name already exists!"
                )

            conn.execute(text("""
                INSERT INTO customers (name, phone, address)
                VALUES (:n, :p, :a)
            """), {
                "n": name,
                "p": request.form["phone"],
                "a": request.form["address"]
            })

        customers_list = fetchall_dict(conn.execute(text("SELECT * FROM customers ORDER BY id DESC")))

    return render_template("customers.html", customers=customers_list)


# =========================================================
# SUPPLIERS
# =========================================================

@app.route("/suppliers", methods=["GET", "POST"])
@permission_required("suppliers")
def suppliers():
    with engine.begin() as conn:
        if request.method == "POST":
            name = request.form["name"].strip()

            # duplicate protection
            dup = conn.execute(text("""
                SELECT id FROM suppliers WHERE LOWER(name) = LOWER(:n)
            """), {"n": name}).fetchone()

            if dup:
                return render_template(
                    "suppliers.html",
                    suppliers=fetchall_dict(conn.execute(text("SELECT * FROM suppliers ORDER BY id DESC"))),
                    error="❌ Supplier name already exists!"
                )

            conn.execute(text("""
                INSERT INTO suppliers (name, phone, address)
                VALUES (:n, :p, :a)
            """), {
                "n": name,
                "p": request.form["phone"],
                "a": request.form["address"]
            })

        suppliers_list = fetchall_dict(conn.execute(text("SELECT * FROM suppliers ORDER BY id DESC")))

    return render_template("suppliers.html", suppliers=suppliers_list)


# =========================================================
# REPORTS
# =========================================================

@app.route("/reports")
@permission_required("reports")
def reports():
    return render_template("reports.html")


@app.route("/reports/stock")
@permission_required("reports")
def report_stock():
    with engine.begin() as conn:
        stock_list = fetchall_dict(conn.execute(text("""
            SELECT p.name, p.volume, ps.current_stock
            FROM product_stock ps
            LEFT JOIN products p ON ps.product_id = p.id
            ORDER BY p.name
        """)))

    return render_template("report_stock.html", stock_list=stock_list)


@app.route("/reports/raw-materials")
@permission_required("reports")
def report_raw_materials():
    with engine.begin() as conn:
        materials = fetchall_dict(conn.execute(text("""
            SELECT * FROM raw_materials ORDER BY name
        """)))

    return render_template("report_raw_materials.html", materials=materials)


@app.route("/reports/production")
@permission_required("reports")
def report_production():
    with engine.begin() as conn:
        production_list = fetchall_dict(conn.execute(text("""
            SELECT pr.*, p.name AS product_name, p.volume
            FROM production pr
            LEFT JOIN products p ON pr.product_id = p.id
            ORDER BY pr.id DESC
        """)))

    return render_template("report_production.html", production_list=production_list)


@app.route("/reports/sales", methods=["GET", "POST"])
@permission_required("reports")
def report_sales():
    sales_list = []

    with engine.begin() as conn:
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

    return render_template("report_sales.html", sales_list=sales_list)


@app.route("/reports/purchase", methods=["GET", "POST"])
@permission_required("reports")
def report_purchase():
    purchase_list = []

    with engine.begin() as conn:
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

    return render_template("report_purchase.html", purchase_list=purchase_list)


# =========================================================
# EXPORT STOCK
# =========================================================

@app.route("/reports/stock/export")
@permission_required("reports")
def export_stock_excel():
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT p.name AS product, p.volume AS volume, ps.current_stock AS stock
            FROM product_stock ps
            LEFT JOIN products p ON ps.product_id = p.id
            ORDER BY p.name
        """)).fetchall()

    df = pd.DataFrame(rows, columns=["Product", "Volume", "Current Stock"])
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)

    output.seek(0)
    return send_file(output, as_attachment=True, download_name="stock_report.xlsx")


# =========================================================
# USERS + PERMISSIONS PANEL
# =========================================================

@app.route("/users", methods=["GET", "POST"])
@permission_required("users")
def users():
    message = None
    error = None

    with engine.begin() as conn:

        # CREATE NEW USER
        if request.method == "POST" and request.form.get("action") == "create_user":
            username = request.form["username"].strip()
            password = request.form["password"].strip()

            if not username or not password:
                error = "Username and password required!"
            else:
                dup = conn.execute(text("""
                    SELECT id FROM users WHERE LOWER(username) = LOWER(:u)
                """), {"u": username}).fetchone()

                if dup:
                    error = "Username already exists!"
                else:
                    hashed = generate_password_hash(password)

                    new_user = conn.execute(text("""
                        INSERT INTO users (username, password, role, is_active)
                        VALUES (:u, :p, 'custom', true)
                        RETURNING id
                    """), {"u": username, "p": hashed}).fetchone()

                    new_user_id = int(new_user[0])

                    # create permissions row
                    conn.execute(text("""
                        INSERT INTO user_permissions (user_id, can_dashboard, can_stock)
                        VALUES (:uid, true, true)
                    """), {"uid": new_user_id})

                    message = "✅ User created successfully!"

        # SAVE PERMISSIONS
        if request.method == "POST" and request.form.get("action") == "save_permissions":
            user_id = int(request.form["user_id"])

            def chk(name):
                return True if request.form.get(name) == "on" else False

            conn.execute(text("""
                UPDATE user_permissions
                SET
                    can_dashboard = :d,
                    can_products = :p,
                    can_raw_materials = :rm,
                    can_bom = :b,
                    can_production = :pr,
                    can_purchase = :pu,
                    can_sales = :s,
                    can_stock = :st,
                    can_customers = :c,
                    can_suppliers = :sp,
                    can_reports = :r,
                    can_users = :u
                WHERE user_id = :uid
            """), {
                "uid": user_id,
                "d": chk("can_dashboard"),
                "p": chk("can_products"),
                "rm": chk("can_raw_materials"),
                "b": chk("can_bom"),
                "pr": chk("can_production"),
                "pu": chk("can_purchase"),
                "s": chk("can_sales"),
                "st": chk("can_stock"),
                "c": chk("can_customers"),
                "sp": chk("can_suppliers"),
                "r": chk("can_reports"),
                "u": chk("can_users"),
            })

            message = "✅ Permissions updated!"

        # RESET PASSWORD
        if request.method == "POST" and request.form.get("action") == "reset_password":
            user_id = int(request.form["user_id"])
            new_password = request.form["new_password"].strip()

            if not new_password:
                error = "Password cannot be empty!"
            else:
                hashed = generate_password_hash(new_password)
                conn.execute(text("""
                    UPDATE users
                    SET password = :p
                    WHERE id = :id
                """), {"p": hashed, "id": user_id})
                message = "✅ Password updated!"

        # TOGGLE ACTIVE
        if request.method == "POST" and request.form.get("action") == "toggle_active":
            user_id = int(request.form["user_id"])

            conn.execute(text("""
                UPDATE users
                SET is_active = NOT is_active
                WHERE id = :id
            """), {"id": user_id})

            message = "✅ User status updated!"

        users_list = fetchall_dict(conn.execute(text("""
            SELECT id, username, is_active
            FROM users
            ORDER BY id
        """)))

        perms_list = fetchall_dict(conn.execute(text("""
            SELECT *
            FROM user_permissions
        """)))

    # merge permissions into users
    perms_map = {p["user_id"]: p for p in perms_list}
    for u in users_list:
        u["permissions"] = perms_map.get(u["id"], {})

    return render_template(
        "users.html",
        users=users_list,
        modules=MODULES,
        message=message,
        error=error
    )


# =========================================================
# LOCAL RUN ONLY
# =========================================================

if __name__ == "__main__":
    app.run(debug=True)
