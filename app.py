import hmac
import os
import sqlite3
from datetime import date
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-fallback-key")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
DATABASE = os.path.join(app.root_path, "supper_club.db")


# ── DB helpers ──────────────────────────────────────────────


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf-8"))


@app.cli.command("init-db")
def init_db_command():
    init_db()
    print("Database initialized.")


with app.app_context():
    init_db()
    db = get_db()
    if not db.execute("SELECT 1 FROM events LIMIT 1").fetchone():
        db.execute(
            "INSERT INTO events (title, date, location, menu_description, capacity) VALUES (?, ?, ?, ?, ?)",
            (
                "March Supper",
                "2026-03-22",
                "555 Bryant Street",
                "TBD",
                14,
            ),
        )
        db.commit()


# ── Auth ────────────────────────────────────────────────────


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin"))
        return f(*args, **kwargs)
    return decorated


# ── Helpers ─────────────────────────────────────────────────


def get_next_event():
    db = get_db()
    return db.execute(
        "SELECT * FROM events WHERE date >= ? ORDER BY date ASC LIMIT 1",
        (date.today().isoformat(),),
    ).fetchone()


def get_registration_count(event_id):
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(num_guests), 0) AS total FROM registrations WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    return row["total"]


# ── Public routes ───────────────────────────────────────────


@app.route("/")
def index():
    event = get_next_event()
    spots_left = None
    if event:
        spots_left = event["capacity"] - get_registration_count(event["id"])
    return render_template("index.html", event=event, spots_left=spots_left)


@app.route("/register", methods=["POST"])
def register():
    event = get_next_event()
    if not event:
        flash("No upcoming event to register for.", "error")
        return redirect(url_for("index"))

    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    dietary = request.form.get("dietary_restrictions", "").strip()
    num_guests = int(request.form.get("num_guests", 1))

    if not name or not phone:
        flash("Name and phone are required.", "error")
        return redirect(url_for("index"))

    if num_guests < 1:
        flash("Must register at least 1 guest.", "error")
        return redirect(url_for("index"))

    spots_left = event["capacity"] - get_registration_count(event["id"])
    if num_guests > spots_left:
        flash("Not enough spots remaining.", "error")
        return redirect(url_for("index"))

    db = get_db()
    cursor = db.execute(
        "INSERT INTO registrations (event_id, name, phone, dietary_restrictions, num_guests) VALUES (?, ?, ?, ?, ?)",
        (event["id"], name, phone, dietary, num_guests),
    )
    db.commit()
    return redirect(url_for("confirmation", reg_id=cursor.lastrowid))


@app.route("/confirmation/<int:reg_id>")
def confirmation(reg_id):
    db = get_db()
    reg = db.execute(
        "SELECT r.*, e.title, e.date, e.location FROM registrations r JOIN events e ON r.event_id = e.id WHERE r.id = ?",
        (reg_id,),
    ).fetchone()
    if not reg:
        flash("Registration not found.", "error")
        return redirect(url_for("index"))
    return render_template("confirmation.html", reg=reg)


# ── Admin routes ────────────────────────────────────────────


@app.route("/admin")
def admin():
    if not session.get("admin"):
        return render_template("admin.html", authed=False)

    db = get_db()
    events = db.execute("SELECT * FROM events ORDER BY date DESC").fetchall()
    event_data = []
    for ev in events:
        regs = db.execute(
            "SELECT * FROM registrations WHERE event_id = ? ORDER BY created_at DESC",
            (ev["id"],),
        ).fetchall()
        total_guests = sum(r["num_guests"] for r in regs)
        event_data.append({"event": ev, "registrations": regs, "total_guests": total_guests})
    return render_template("admin.html", authed=True, event_data=event_data, today=date.today().isoformat())


@app.route("/admin/login", methods=["POST"])
def admin_login():
    password = request.form.get("password", "")
    if hmac.compare_digest(password, ADMIN_PASSWORD):
        session["admin"] = True
        flash("Logged in.", "success")
    else:
        flash("Incorrect password.", "error")
    return redirect(url_for("admin"))


@app.route("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/events", methods=["POST"])
@admin_required
def create_event():
    title = request.form.get("title", "").strip()
    event_date = request.form.get("date", "").strip()
    location = request.form.get("location", "").strip()
    menu_description = request.form.get("menu_description", "").strip()
    capacity = int(request.form.get("capacity", 0))

    if not all([title, event_date, location, menu_description, capacity]):
        flash("All fields are required.", "error")
        return redirect(url_for("admin"))

    db = get_db()
    db.execute(
        "INSERT INTO events (title, date, location, menu_description, capacity) VALUES (?, ?, ?, ?, ?)",
        (title, event_date, location, menu_description, capacity),
    )
    db.commit()
    flash("Event created.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/events/<int:event_id>", methods=["POST"])
@admin_required
def update_event(event_id):
    title = request.form.get("title", "").strip()
    event_date = request.form.get("date", "").strip()
    location = request.form.get("location", "").strip()
    menu_description = request.form.get("menu_description", "").strip()
    capacity = int(request.form.get("capacity", 0))

    db = get_db()
    db.execute(
        "UPDATE events SET title=?, date=?, location=?, menu_description=?, capacity=? WHERE id=?",
        (title, event_date, location, menu_description, capacity, event_id),
    )
    db.commit()
    flash("Event updated.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/events/<int:event_id>/delete", methods=["POST"])
@admin_required
def delete_event(event_id):
    db = get_db()
    db.execute("DELETE FROM registrations WHERE event_id = ?", (event_id,))
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db.commit()
    flash("Event deleted.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/registrations/<int:reg_id>", methods=["POST"])
@admin_required
def update_registration(reg_id):
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    num_guests = int(request.form.get("num_guests", 1))
    dietary = request.form.get("dietary_restrictions", "").strip()

    db = get_db()
    db.execute(
        "UPDATE registrations SET name=?, phone=?, num_guests=?, dietary_restrictions=? WHERE id=?",
        (name, phone, num_guests, dietary, reg_id),
    )
    db.commit()
    flash("Guest updated.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/registrations/<int:reg_id>/delete", methods=["POST"])
@admin_required
def delete_registration(reg_id):
    db = get_db()
    db.execute("DELETE FROM registrations WHERE id = ?", (reg_id,))
    db.commit()
    flash("Guest removed.", "success")
    return redirect(url_for("admin"))
