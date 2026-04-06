from flask import Flask, render_template, jsonify, request, session, redirect, g
import oracledb

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config['SESSION_COOKIE_SAMESITE'] = "Lax"
app.config['SESSION_COOKIE_SECURE'] = False
DB_DSN = "localhost/XEPDB1"

def get_connection():
    user = session.get("user")
    pwd  = session.get("pwd")

    if not user or not pwd:
        raise Exception("Not logged in")

    return oracledb.connect(user=user, password=pwd, dsn=DB_DSN)

def query(sql, params=None):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        cols = [c[0].lower() for c in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        return rows
    finally:
        conn.close()

def execute(sql, params=None):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        conn.commit()
        cur.close()
    except:
        conn.rollback()
        raise
    finally:
        conn.close()

def role():
    return session.get("role", "viewer")

def require_login():
    if not session.get("user"):
        return jsonify({"error": "Not logged in"}), 401
    return None

@app.route("/")
def index():
    if not session.get("user"):
        return redirect("/login")
    return render_template("index.html", user=session.get("user"), role=session.get("role"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        d = request.json
        username = d.get("username", "").lower().strip()
        password = d.get("password", "").strip()
        try:
            conn = oracledb.connect(user=username, password=password, dsn=DB_DSN)
            conn.close()
            session["user"] = username
            session["pwd"]  = password
            roles = {"scm_admin": "admin", "scm_employee": "employee", "scm_tracker": "tracker"}
            session["role"] = roles.get(username, "viewer")
            return jsonify({"success": True, "role": session["role"]})
        except Exception as e:
            return jsonify({"success": False, "error": "Invalid username or password"})
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/api/me")
def me():
    return jsonify({"user": session.get("user"), "role": session.get("role")})

# Products

@app.route("/api/products", methods=["GET"])
def get_products():
    err = require_login()
    if err: return err
    if role() == "tracker": return jsonify({"error": "Access denied"}), 403
    return jsonify(query("SELECT * FROM product ORDER BY product_id"))

@app.route("/api/products", methods=["POST"])
def add_product():
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    d = request.json
    execute("INSERT INTO product VALUES (:1,:2,:3,:4)", [d["product_id"], d["product_name"], d["description"], d["price"]])
    return jsonify({"message": "Product added successfully"})

@app.route("/api/products/<int:pid>", methods=["DELETE"])
def delete_product(pid):
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    execute("DELETE FROM product WHERE product_id = :1", [pid])
    return jsonify({"message": "Product deleted successfully"})

# Warehouses

@app.route("/api/warehouses", methods=["GET"])
def get_warehouses():
    err = require_login()
    if err: return err
    return jsonify(query("SELECT * FROM warehouse ORDER BY warehouse_id"))

@app.route("/api/warehouses/stock", methods=["GET"])
def warehouse_stock():
    err = require_login()
    if err: return err
    return jsonify(query("SELECT w.location, SUM(i.quantity) AS total_stock FROM inventory i JOIN warehouse w ON i.warehouse_id=w.warehouse_id GROUP BY w.location ORDER BY total_stock DESC"))

# Inventory

@app.route("/api/inventory", methods=["GET"])
def get_inventory():
    err = require_login()
    if err: return err
    return jsonify(query("SELECT p.product_name, w.location AS warehouse, i.quantity, CASE WHEN i.quantity<10 THEN 'Critical' WHEN i.quantity<20 THEN 'Low' ELSE 'Adequate' END AS stock_status FROM inventory i JOIN product p ON i.product_id=p.product_id JOIN warehouse w ON i.warehouse_id=w.warehouse_id ORDER BY i.quantity ASC"))

@app.route("/api/inventory/low-stock", methods=["GET"])
def low_stock():
    err = require_login()
    if err: return err
    return jsonify(query("SELECT p.product_name, w.location, i.quantity FROM inventory i JOIN product p ON i.product_id=p.product_id JOIN warehouse w ON i.warehouse_id=w.warehouse_id WHERE i.quantity<20 ORDER BY i.quantity ASC"))

# Clients

@app.route("/api/clients", methods=["GET"])
def get_clients():
    err = require_login()
    if err: return err
    return jsonify(query("SELECT * FROM client ORDER BY client_id"))

@app.route("/api/clients", methods=["POST"])
def add_client():
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    d = request.json
    execute("INSERT INTO client VALUES (:1,:2,:3)", [d["client_id"], d["name"], d["address"]])
    return jsonify({"message": "Client added successfully"})

@app.route("/api/clients/<int:cid>", methods=["DELETE"])
def delete_client(cid):
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    execute("DELETE FROM client WHERE client_id=:1", [cid])
    return jsonify({"message": "Client deleted successfully"})

# Orders

@app.route("/api/orders", methods=["GET"])
def get_orders():
    err = require_login()
    if err: return err
    if role() == "tracker": return jsonify({"error": "Access denied"}), 403
    return jsonify(query("SELECT o.order_id, c.name AS client_name, o.client_id, TO_CHAR(o.order_date,'DD-MON-YYYY') AS order_date, o.status FROM orders o JOIN client c ON o.client_id=c.client_id ORDER BY o.order_id"))

@app.route("/api/orders", methods=["POST"])
def add_order():
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    d = request.json
    execute("INSERT INTO orders VALUES (:1,:2,SYSDATE,:3)", [d["order_id"], d["client_id"], d["status"]])
    return jsonify({"message": "Order placed successfully"})

@app.route("/api/orders/<int:oid>/status", methods=["PUT"])
def update_order_status(oid):
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    d = request.json
    execute("UPDATE orders SET status=:1 WHERE order_id=:2", [d["status"], oid])
    return jsonify({"message": "Order status updated"})

@app.route("/api/orders/<int:oid>", methods=["DELETE"])
def delete_order(oid):
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    execute("DELETE FROM orders WHERE order_id=:1", [oid])
    return jsonify({"message": "Order deleted successfully"})

# Shipments

@app.route("/api/shipments", methods=["GET"])
def get_shipments():
    err = require_login()
    if err: return err

    data = query("""
        SELECT s.shipment_id, s.order_id, c.name AS client_name,
               d.name AS driver_name, s.status AS shipment_status
        FROM shipment s
        JOIN orders o ON s.order_id = o.order_id
        JOIN client c ON o.client_id = c.client_id
        JOIN driver d ON s.driver_id = d.driver_id
    """)

    if role() == "tracker":
        return jsonify([
            {
                "shipment_id": s["shipment_id"],
                "order_id": s["order_id"],
                "shipment_status": s["shipment_status"]
            } for s in data
        ])

    return jsonify(data)

@app.route("/api/shipments", methods=["POST"])
def add_shipment():
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    d = request.json
    execute(
        "INSERT INTO shipment VALUES (:1,:2,:3,:4)",
        [d["shipment_id"], d["order_id"], d["driver_id"], d["status"]]
    )
    return jsonify({"message": "Shipment created successfully"})

@app.route("/api/shipments/<int:sid>/status", methods=["PUT"])
def update_shipment_status(sid):
    err = require_login()
    if err: return err

    if role() not in ("employee", "admin"):
        return jsonify({"error": "Access denied"}), 403

    d = request.json
    execute("UPDATE shipment SET status=:1 WHERE shipment_id=:2", [d["status"], sid])
    return jsonify({"message": "Shipment status updated"})

# Drivers

@app.route("/api/drivers", methods=["GET"])
def get_drivers():
    err = require_login()
    if err: return err
    return jsonify(query("SELECT * FROM driver ORDER BY driver_id"))

@app.route("/api/drivers", methods=["POST"])
def add_driver():
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    d = request.json
    execute("INSERT INTO driver VALUES (:1,:2,:3)", [d["driver_id"], d["name"], d["license_no"]])
    return jsonify({"message": "Driver added successfully"})

@app.route("/api/drivers/<int:did>", methods=["DELETE"])
def delete_driver(did):
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    execute("DELETE FROM driver WHERE driver_id=:1", [did])
    return jsonify({"message": "Driver deleted successfully"})

# Vehicles

@app.route("/api/vehicles", methods=["GET"])
def get_vehicles():
    err = require_login()
    if err: return err
    return jsonify(query("SELECT * FROM vehicle ORDER BY vehicle_id"))

@app.route("/api/vehicles", methods=["POST"])
def add_vehicle():
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    d = request.json
    execute("INSERT INTO vehicle VALUES (:1,:2,:3)", [d["vehicle_id"], d["vehicle_type"], d["capacity"]])
    return jsonify({"message": "Vehicle added successfully"})

@app.route("/api/vehicles/<int:vid>", methods=["DELETE"])
def delete_vehicle(vid):
    err = require_login()
    if err: return err
    if role() != "admin": return jsonify({"error": "Access denied"}), 403
    execute("DELETE FROM vehicle WHERE vehicle_id=:1", [vid])
    return jsonify({"message": "Vehicle deleted successfully"})

# Dashboard

@app.route("/api/dashboard", methods=["GET"])
def dashboard():
    err = require_login()
    if err: return err
    stats = {}
    if role() == "tracker":
        stats["total_shipments"] = query("SELECT COUNT(*) AS cnt FROM shipment")[0]["cnt"]
        stats["delivered"]       = query("SELECT COUNT(*) AS cnt FROM shipment WHERE status='Delivered'")[0]["cnt"]
        stats["in_transit"]      = query("SELECT COUNT(*) AS cnt FROM shipment WHERE status='In Transit'")[0]["cnt"]
        stats["total_products"]  = "—"
        stats["total_orders"]    = "—"
        stats["total_inventory"] = "—"
        stats["pending_orders"]  = "—"
        stats["warehouse_stock"] = []
        stats["low_stock_count"] = "—"
        stats["recent_orders"]   = []
        return jsonify(stats)
    stats["total_products"]  = query("SELECT COUNT(*) AS cnt FROM product")[0]["cnt"]
    stats["total_orders"]    = query("SELECT COUNT(*) AS cnt FROM orders")[0]["cnt"]
    stats["total_inventory"] = query("SELECT NVL(SUM(quantity),0) AS cnt FROM inventory")[0]["cnt"]
    stats["total_shipments"] = query("SELECT COUNT(*) AS cnt FROM shipment")[0]["cnt"]
    stats["delivered"]       = query("SELECT COUNT(*) AS cnt FROM shipment WHERE status='Delivered'")[0]["cnt"]
    stats["in_transit"]      = query("SELECT COUNT(*) AS cnt FROM shipment WHERE status='In Transit'")[0]["cnt"]
    stats["pending_orders"]  = query("SELECT COUNT(*) AS cnt FROM orders WHERE status='Pending'")[0]["cnt"]
    stats["warehouse_stock"] = query("SELECT w.location, SUM(i.quantity) AS total_stock FROM inventory i JOIN warehouse w ON i.warehouse_id=w.warehouse_id GROUP BY w.location ORDER BY total_stock DESC")
    stats["low_stock_count"] = query("SELECT COUNT(*) AS cnt FROM inventory WHERE quantity<20")[0]["cnt"]
    stats["recent_orders"]   = query("SELECT o.order_id, c.name AS client_name, o.status FROM orders o JOIN client c ON o.client_id=c.client_id ORDER BY o.order_id DESC FETCH FIRST 5 ROWS ONLY")
    return jsonify(stats)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
