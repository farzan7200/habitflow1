from flask import Flask, render_template, request, redirect, session, g, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3
from datetime import date, timedelta

app = Flask(__name__)
app.secret_key = "replace-with-secure-key"   # IMPORTANT: change before submit

DATABASE = "habits.db"

# ------------------------ DATABASE ------------------------
def get_db():
    if "_db" not in g:
        g._db = sqlite3.connect(DATABASE)
        g._db.row_factory = sqlite3.Row
    return g._db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("_db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    cur = db.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS habit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY(habit_id) REFERENCES habits(id)
        );
    """)

    db.commit()

# ------------------------ AUTH HELPERS ------------------------
def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

# ------------------------ ROUTES ------------------------

@app.route("/")
def index():
    return render_template("index.html")

# ---------- REGISTER ----------
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        confirm  = request.form.get("confirm","")

        if not username or not password:
            flash("Please provide username & password.", "danger")
            return redirect(url_for("register"))

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))

        db = get_db()
        cur = db.cursor()

        try:
            cur.execute("INSERT INTO users (username, hash) VALUES (?,?)",
                        (username, generate_password_hash(password)))
            db.commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists.", "danger")

    return render_template("register.html")

# ---------- LOGIN ----------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")

        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cur.fetchone()

        if user and check_password_hash(user["hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = username
            flash("Welcome!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")

# ---------- LOGOUT ----------
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("index"))

# ---------- DASHBOARD ----------
@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT * FROM habits WHERE user_id = ?", (session["user_id"],))
    habits = cur.fetchall()

    today = date.today().isoformat()
    done_map = {}

    for h in habits:
        cur.execute("SELECT 1 FROM habit_logs WHERE habit_id = ? AND date = ?", (h["id"], today))
        done_map[h["id"]] = cur.fetchone() is not None

    return render_template("dashboard.html", habits=habits, done_map=done_map)

# ---------- ADD HABIT ----------
@app.route("/add", methods=["POST"])
@login_required
def add():
    name = request.form.get("habit","").strip()
    if not name:
        flash("Habit name cannot be empty.", "danger")
        return redirect(url_for("dashboard"))

    db = get_db()
    cur = db.cursor()
    cur.execute("INSERT INTO habits (user_id, name) VALUES (?,?)", (session["user_id"], name))
    db.commit()
    flash("Habit added.", "success")
    return redirect(url_for("dashboard"))

# ---------- EDIT HABIT ----------
@app.route("/edit/<int:hid>", methods=["GET","POST"])
@login_required
def edit(hid):
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT * FROM habits WHERE id = ? AND user_id = ?", (hid, session["user_id"]))
    habit = cur.fetchone()
    if not habit:
        flash("Habit not found.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        new_name = request.form.get("habit","").strip()
        if not new_name:
            flash("Habit name cannot be empty.", "danger")
            return redirect(url_for("edit", hid=hid))

        cur.execute("UPDATE habits SET name = ? WHERE id = ?", (new_name, hid))
        db.commit()
        flash("Habit updated.", "success")
        return redirect(url_for("dashboard"))

    return render_template("edit_habit.html", habit=habit)

# ---------- DELETE HABIT ----------
@app.route("/delete/<int:hid>", methods=["POST"])
@login_required
def delete(hid):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM habit_logs WHERE habit_id = ?", (hid,))
    cur.execute("DELETE FROM habits WHERE id = ? AND user_id = ?", (hid, session["user_id"]))
    db.commit()

    flash("Habit deleted.", "info")
    return redirect(url_for("dashboard"))

# ---------- MARK DONE ----------
@app.route("/done/<int:hid>", methods=["POST"])
@login_required
def done(hid):
    today = date.today().isoformat()

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT 1 FROM habit_logs WHERE habit_id = ? AND date = ?", (hid, today))
    if cur.fetchone():
        flash("Already marked today.", "warning")
    else:
        cur.execute("INSERT INTO habit_logs (habit_id, date) VALUES (?,?)", (hid, today))
        db.commit()
        flash("Marked as done.", "success")

    return redirect(url_for("dashboard"))

# ---------- HISTORY ----------
@app.route("/history/<int:hid>")
@login_required
def history(hid):
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT * FROM habits WHERE id = ? AND user_id = ?", (hid, session["user_id"]))
    habit = cur.fetchone()
    if not habit:
        flash("Habit not found.", "danger")
        return redirect(url_for("dashboard"))

    cur.execute("SELECT date FROM habit_logs WHERE habit_id = ? ORDER BY date DESC", (hid,))
    logs = cur.fetchall()

    return render_template("habit_history.html", habit=habit, logs=logs)

# ---------- DARK MODE ----------
@app.route("/toggle_theme", methods=["POST"])
def toggle_theme():
    current = session.get("theme", "light")
    session["theme"] = "dark" if current == "light" else "light"

    return redirect(request.referrer or url_for("index"))

# ------------------------ RUN APP ------------------------
if __name__ == "__main__":
    # FIX: proper app context for init_db()
    with app.app_context():
        init_db()
    app.run(debug=True)



