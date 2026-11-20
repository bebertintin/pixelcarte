"""PixelCarte : serveur Python (Flask + SQLite). Comptes, créations, formulaire de contact."""
import os, re, json, time, hmac, sqlite3, smtplib
from email.message import EmailMessage
from datetime import datetime, timezone
from flask import Flask, request, session, jsonify, g, send_from_directory
from flask.sessions import SecureCookieSessionInterface
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR", os.path.join(BASE, "data"))
os.makedirs(DATA, exist_ok=True)
DB = os.path.join(DATA, "pixelcarte.db")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def secret():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    p = os.path.join(DATA, "secret.key")
    if not os.path.exists(p):
        with open(p, "w") as f:
            f.write(os.urandom(32).hex())
    return open(p).read()


app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="/static")
app.secret_key = secret()
app.config.update(
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
)

class Sess(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):  # cookie « Secure » seulement si la page est en HTTPS
        return request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https"


app.session_interface = Sess()

with sqlite3.connect(DB) as c:
    c.executescript("""
    create table if not exists users(id integer primary key, email text unique not null, pw text not null, created text not null);
    create table if not exists creations(id integer primary key, user_id integer not null references users(id) on delete cascade, name text not null, data text not null, created text not null);
    create table if not exists messages(id integer primary key, name text, email text, message text, ip text, created text not null);
    """)


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("pragma foreign_keys=on")
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fail(msg, code=400):
    return jsonify(error=msg), code


def ip():
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?")


HITS = {}


def limited(key, n, per):
    t = time.time()
    h = [x for x in HITS.get(key, []) if t - x < per]
    over = len(h) >= n
    if not over:
        h.append(t)
    HITS[key] = h
    return over


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return db().execute("select id,email from users where id=?", (uid,)).fetchone()


@app.before_request
def need_json():
    if request.path.startswith("/api/") and request.method in ("POST", "PUT") and not request.is_json:
        return fail("JSON attendu.", 415)


@app.after_request
def headers(r):
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return r


@app.errorhandler(413)
def too_big(_):
    return fail("Fichier trop volumineux.", 413)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------- comptes ----------
@app.post("/api/register")
def register():
    b = request.get_json(silent=True) or {}
    email, pw = str(b.get("email", "")).strip().lower(), str(b.get("password", ""))
    if limited("reg" + ip(), 10, 3600):
        return fail("Trop de tentatives, réessaie plus tard.", 429)
    if not EMAIL_RE.match(email):
        return fail("E-mail invalide.")
    if len(pw) < 8 or len(pw) > 200:
        return fail("Mot de passe : 8 caractères minimum.")
    try:
        cur = db().execute("insert into users(email,pw,created) values(?,?,?)", (email, generate_password_hash(pw), now()))
        db().commit()
    except sqlite3.IntegrityError:
        return fail("Un compte existe déjà avec cet e-mail.", 409)
    session.clear()
    session["uid"] = cur.lastrowid
    session.permanent = True
    return jsonify(user={"email": email})


@app.post("/api/login")
def login():
    b = request.get_json(silent=True) or {}
    email, pw = str(b.get("email", "")).strip().lower(), str(b.get("password", ""))
    if limited("log" + ip() + email, 10, 600):
        return fail("Trop de tentatives, réessaie dans quelques minutes.", 429)
    u = db().execute("select * from users where email=?", (email,)).fetchone()
    if not u or not check_password_hash(u["pw"], pw):
        return fail("E-mail ou mot de passe incorrect.", 401)
    session.clear()
    session["uid"] = u["id"]
    session.permanent = True
    return jsonify(user={"email": u["email"]})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    u = current_user()
    return jsonify(user={"email": u["email"]} if u else None)


# ---------- créations ----------
@app.get("/api/creations")
def list_creations():
    u = current_user()
    if not u:
        return fail("Connexion requise.", 401)
    rows = db().execute("select id,name,created,json_extract(data,'$.thumb') as thumb from creations where user_id=? order by id desc", (u["id"],)).fetchall()
    return jsonify(creations=[dict(r) for r in rows])


@app.post("/api/creations")
def add_creation():
    u = current_user()
    if not u:
        return fail("Connexion requise.", 401)
    b = request.get_json(silent=True) or {}
    name, d = str(b.get("name", "")).strip()[:60] or "Sans titre", b.get("data")
    if not isinstance(d, dict) or not str(d.get("image", "")).startswith("data:image/") or not isinstance(d.get("settings"), dict):
        return fail("Création invalide.")
    if len(json.dumps(d)) > 4_000_000:
        return fail("Image trop volumineuse.", 413)
    if db().execute("select count(*) from creations where user_id=?", (u["id"],)).fetchone()[0] >= 50:
        return fail("Limite de 50 créations atteinte.", 403)
    cur = db().execute("insert into creations(user_id,name,data,created) values(?,?,?,?)", (u["id"], name, json.dumps(d), now()))
    db().commit()
    return jsonify(id=cur.lastrowid)


@app.get("/api/creations/<int:cid>")
def get_creation(cid):
    u = current_user()
    if not u:
        return fail("Connexion requise.", 401)
    r = db().execute("select name,data from creations where id=? and user_id=?", (cid, u["id"])).fetchone()
    if not r:
        return fail("Introuvable.", 404)
    return jsonify(creation={"name": r["name"], "data": json.loads(r["data"])})


@app.delete("/api/creations/<int:cid>")
def del_creation(cid):
    u = current_user()
    if not u:
        return fail("Connexion requise.", 401)
    db().execute("delete from creations where id=? and user_id=?", (cid, u["id"]))
    db().commit()
    return jsonify(ok=True)


# ---------- contact ----------
@app.post("/api/contact")
def contact():
    b = request.get_json(silent=True) or {}
    name, email, msg = str(b.get("name", "")).strip()[:80], str(b.get("email", "")).strip()[:120], str(b.get("message", "")).strip()[:2000]
    if not name or not msg or not EMAIL_RE.match(email):
        return fail("Remplis ton nom, un e-mail valide et un message.")
    if limited("ct" + ip(), 5, 3600):
        return fail("Trop de messages, réessaie plus tard.", 429)
    db().execute("insert into messages(name,email,message,ip,created) values(?,?,?,?,?)", (name, email, msg, ip(), now()))
    db().commit()
    host, to = os.environ.get("SMTP_HOST"), os.environ.get("MAIL_TO")
    if host and to:  # envoi d'un e-mail si le SMTP est configuré
        try:
            m = EmailMessage()
            m["Subject"], m["From"], m["To"], m["Reply-To"] = "Message depuis PixelCarte", os.environ.get("SMTP_USER", to), to, email
            m.set_content(f"Nom : {name}\nE-mail : {email}\n\n{msg}")
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=10) as s:
                s.starttls()
                if os.environ.get("SMTP_USER"):
                    s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
                s.send_message(m)
        except Exception:
            pass  # le message reste enregistré en base
    return jsonify(ok=True)


@app.get("/admin/messages")
def admin_messages():
    key = os.environ.get("ADMIN_KEY")
    if not key:
        return fail("Introuvable.", 404)
    if not hmac.compare_digest(request.args.get("key", ""), key):
        return fail("Interdit.", 403)
    rows = db().execute("select id,name,email,message,created from messages order by id desc limit 200").fetchall()
    return jsonify(messages=[dict(r) for r in rows])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("SERVER_PORT") or os.environ.get("PORT") or 8000))
