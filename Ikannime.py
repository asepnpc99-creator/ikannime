
import os
import uuid
import sqlite3
import secrets
from functools import wraps

from flask import (
    Flask, request, redirect, url_for, session, flash,
    abort, send_from_directory, render_template_string
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
UPLOADS = os.path.join(DATA, "uploads")
DB_PATH = os.path.join(DATA, "ikannime.db")
os.makedirs(UPLOADS, exist_ok=True)

VIDEOS = {"mp4", "webm", "mov", "m4v", "ogv"}
IMAGES = {"jpg", "jpeg", "png", "webp", "gif"}
STICKERS = ["😀", "😂", "😍", "😭", "😎", "🥰", "🔥", "❤️",
            "👍", "🤣", "😱", "✨", "💯", "🐱", "🍿"]

def connect_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db

def init_db():
    db = connect_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS posts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        title TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'video',
        created TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS comments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        message TEXT DEFAULT '',
        sticker TEXT DEFAULT '',
        created TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    # Migrasi database versi lama.
    cols = {r["name"] for r in db.execute("PRAGMA table_info(posts)")}
    if "kind" not in cols:
        db.execute("ALTER TABLE posts ADD COLUMN kind TEXT DEFAULT 'video'")
    comment_cols = {
        r["name"] for r in db.execute("PRAGMA table_info(comments)")
    }
    if "sticker" not in comment_cols:
        db.execute("ALTER TABLE comments ADD COLUMN sticker TEXT DEFAULT ''")
    db.commit()
    db.close()

init_db()

def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    db = connect_db()
    user = db.execute(
        "SELECT id,username FROM users WHERE id=?", (uid,)
    ).fetchone()
    db.close()
    return user

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Login dulu untuk menggunakan fitur ini.")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]

app.jinja_env.globals["csrf_token"] = csrf_token

@app.before_request
def verify_csrf():
    if request.method == "POST":
        given = request.form.get("csrf_token", "")
        expected = session.get("csrf", "")
        if not given or not expected or not secrets.compare_digest(
            given, expected
        ):
            abort(400, "Form tidak valid. Muat ulang halaman.")

STYLE = """
<style>
*{box-sizing:border-box}
body{margin:0;background:#080d18;color:#edf3ff;font-family:Arial,sans-serif}
header{background:#111b30;padding:15px;display:flex;align-items:center;
justify-content:space-between;gap:12px;flex-wrap:wrap}
.brand{font-size:24px;font-weight:bold;color:#55b8ff;text-decoration:none;
display:inline-flex;align-items:center;gap:8px}
nav{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
a{color:#83c9ff;text-decoration:none}
main{max-width:900px;margin:20px auto;padding:0 12px}
.card{background:#121d32;border:1px solid #283954;border-radius:14px;
padding:15px;margin-bottom:16px;overflow-wrap:anywhere}
input,textarea{width:100%;padding:11px;margin:6px 0;background:#0a1324;
color:white;border:1px solid #354664;border-radius:8px}
button,.btn{background:#1479e8;color:white;padding:10px 14px;border:0;
border-radius:8px;cursor:pointer;display:inline-block}
.secondary{background:#2a3954}.danger{background:#bb304b}
.media{width:100%;max-height:70vh;object-fit:contain;background:#05070a;
border-radius:9px}
.muted{color:#9eacc4;font-size:13px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.stickers button{font-size:24px;background:#283954;padding:6px;margin:3px}
.comment{padding:12px 0;border-bottom:1px solid #2a3852}
@media(max-width:500px){.brand{font-size:21px}header{padding:12px}}
</style>
"""

def page(title, content, **kwargs):
    return render_template_string("""
    <!doctype html><html lang="id"><head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{{ title }} - Ikannime</title>
    """ + STYLE + """
    </head><body>
    <header>
      <a class="brand" href="{{ url_for('home') }}">🐡 Ikannime</a>
      <nav>
        <a href="{{ url_for('home') }}">Beranda</a>
        {% if user %}
          <span>{{ user.username }}</span>
          <a href="{{ url_for('logout') }}">Keluar</a>
        {% else %}
          <a href="{{ url_for('login') }}">Login</a>
          <a href="{{ url_for('register') }}">Daftar</a>
        {% endif %}
      </nav>
    </header>
    <main>
      {% for msg in get_flashed_messages() %}
        <div class="card">{{ msg }}</div>
      {% endfor %}
      """ + content + """
    </main></body></html>
    """, title=title, user=current_user(), **kwargs)

@app.route("/")
def home():
    db = connect_db()
    posts = db.execute("""
        SELECT p.*,u.username FROM posts p
        JOIN users u ON u.id=p.user_id ORDER BY p.id DESC
    """).fetchall()
    db.close()

    content = """
    <div class="card">
      <h2>Selamat datang di Ikannime 🐡</h2>
      <form action="{{ url_for('search') }}" method="get">
        <input name="q" placeholder="Cari video atau gambar...">
        <button>Cari</button>
      </form>
      {% if user %}
        <p><a class="btn" href="{{ url_for('upload') }}">＋ Upload media</a></p>
      {% else %}
        <p>Login untuk upload, komentar, dan kirim stiker.</p>
      {% endif %}
    </div>

    {% for p in posts %}
    <div class="card">
      <div class="muted">{{ p.username }} · {{ p.kind }}</div>
      <h3>{{ p.title }}</h3>
      <a href="{{ url_for('watch',pid=p.id) }}">
      {% if p.kind == 'image' %}
        <img class="media" loading="lazy"
        src="{{ url_for('media',filename=p.filename) }}" alt="{{ p.title }}">
      {% else %}
        <video class="media" preload="metadata"
        src="{{ url_for('media',filename=p.filename) }}"></video>
      {% endif %}
      </a>
      <p><a class="btn" href="{{ url_for('watch',pid=p.id) }}">
      Buka postingan · Komentar</a></p>
    </div>
    {% else %}
    <div class="card">Belum ada postingan. Upload yang pertama!</div>
    {% endfor %}
    """
    return page("Beranda", content, posts=posts)

@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    db = connect_db()
    posts = db.execute("""
        SELECT p.*,u.username FROM posts p
        JOIN users u ON u.id=p.user_id
        WHERE p.title LIKE ? ORDER BY p.id DESC
    """, ("%" + q + "%",)).fetchall()
    db.close()

    content = """
    <div class="card"><h2>Hasil pencarian</h2>
      <form><input name="q" value="{{ q }}" placeholder="Cari...">
      <button>Cari</button></form>
    </div>
    {% for p in posts %}
    <div class="card">
      <div class="muted">{{ p.username }} · {{ p.kind }}</div>
      <h3><a href="{{ url_for('watch',pid=p.id) }}">{{ p.title }}</a></h3>
      {% if p.kind == 'image' %}
        <a href="{{ url_for('watch',pid=p.id) }}">
        <img class="media" src="{{ url_for('media',filename=p.filename) }}"></a>
      {% else %}
        <a href="{{ url_for('watch',pid=p.id) }}">Tonton video ▶</a>
      {% endif %}
    </div>
    {% else %}<div class="card">Tidak ditemukan.</div>{% endfor %}
    """
    return page("Pencarian", content, posts=posts, q=q)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not 3 <= len(username) <= 30:
            flash("Username harus 3–30 karakter.")
        elif len(password) < 6:
            flash("Kata sandi minimal 6 karakter.")
        else:
            db = connect_db()
            try:
                cur = db.execute(
                    "INSERT INTO users(username,password) VALUES(?,?)",
                    (username, generate_password_hash(password))
                )
                db.commit()
                session.clear()
                session["uid"] = cur.lastrowid
                db.close()
                return redirect(url_for("home"))
            except sqlite3.IntegrityError:
                db.close()
                flash("Username sudah digunakan.")

    content = """
    <div class="card"><h2>Daftar akun</h2>
    <form method="post">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input name="username" required minlength="3" maxlength="30"
      placeholder="Username">
      <input name="password" type="password" required minlength="6"
      placeholder="Kata sandi">
      <button>Daftar</button>
    </form></div>
    """
    return page("Daftar", content)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        db = connect_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=?",
            (request.form.get("username", "").strip(),)
        ).fetchone()
        db.close()
        if user and check_password_hash(
            user["password"], request.form.get("password", "")
        ):
            session.clear()
            session["uid"] = user["id"]
            return redirect(url_for("home"))
        flash("Username atau kata sandi salah.")

    content = """
    <div class="card"><h2>Login</h2>
    <form method="post">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input name="username" required placeholder="Username">
      <input name="password" type="password" required placeholder="Kata sandi">
      <button>Login</button>
    </form>
    <p>Belum punya akun? <a href="{{ url_for('register') }}">Daftar</a></p>
    </div>
    """
    return page("Login", content)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:150]
        file = request.files.get("file")
        if not title or not file or not file.filename:
            flash("Isi judul dan pilih file.")
            return redirect(url_for("upload"))

        safe = secure_filename(file.filename)
        if "." not in safe:
            flash("Format file tidak dikenali.")
            return redirect(url_for("upload"))
        ext = safe.rsplit(".", 1)[1].lower()

        if ext in VIDEOS:
            kind = "video"
        elif ext in IMAGES:
            kind = "image"
        else:
            flash("Format video MP4/WebM/MOV atau gambar JPG/PNG/WEBP/GIF.")
            return redirect(url_for("upload"))

        data = file.read()
        if not data:
            flash("File kosong.")
            return redirect(url_for("upload"))
        if kind == "image" and len(data) > 10 * 1024 * 1024:
            flash("Gambar maksimal 10 MB.")
            return redirect(url_for("upload"))

        filename = uuid.uuid4().hex + "." + ext
        with open(os.path.join(UPLOADS, filename), "wb") as f:
            f.write(data)

        db = connect_db()
        db.execute("""
            INSERT INTO posts(user_id,filename,title,kind)
            VALUES(?,?,?,?)
        """, (session["uid"], filename, title, kind))
        db.commit()
        db.close()
        flash("Upload berhasil!")
        return redirect(url_for("home"))

    content = """
    <div class="card"><h2>Upload video atau gambar</h2>
    <form method="post" enctype="multipart/form-data">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input name="title" maxlength="150" required placeholder="Judul postingan">
      <input type="file" name="file" required
      accept="video/*,image/jpeg,image/png,image/webp,image/gif">
      <p class="muted">Gambar maksimal 10 MB. Batas total upload 500 MB.</p>
      <button>Upload</button>
    </form></div>
    """
    return page("Upload", content)

@app.route("/media/<path:filename>")
def media(filename):
    if os.path.basename(filename) != filename:
        abort(404)
    return send_from_directory(UPLOADS, filename)

@app.route("/watch/<int:pid>", methods=["GET", "POST"])
def watch(pid):
    db = connect_db()
    post = db.execute("""
        SELECT p.*,u.username FROM posts p
        JOIN users u ON u.id=p.user_id WHERE p.id=?
    """, (pid,)).fetchone()
    if not post:
        db.close()
        abort(404)

    if request.method == "POST":
        if not current_user():
            db.close()
            flash("Login dulu untuk berkomentar.")
            return redirect(url_for("login"))

        if request.form.get("action") == "delete_comment":
            cid = request.form.get("cid", type=int)
            db.execute("""
                DELETE FROM comments WHERE id=? AND post_id=? AND user_id=?
            """, (cid, pid, session["uid"]))
            db.commit()
            db.close()
            return redirect(url_for("watch", pid=pid))

        message = request.form.get("message", "").strip()[:1000]
        sticker = request.form.get("sticker", "")
        if sticker not in STICKERS:
            sticker = ""
        if message or sticker:
            db.execute("""
                INSERT INTO comments(post_id,user_id,message,sticker)
                VALUES(?,?,?,?)
            """, (pid, session["uid"], message, sticker))
            db.commit()
        else:
            flash("Tulis komentar atau pilih stiker.")
        db.close()
        return redirect(url_for("watch", pid=pid))

    comments = db.execute("""
        SELECT c.*,u.username FROM comments c
        JOIN users u ON u.id=c.user_id
        WHERE c.post_id=? ORDER BY c.id ASC
    """, (pid,)).fetchall()
    db.close()

    content = """
    <div class="card">
      <div class="muted">{{ post.username }} · {{ post.kind }}</div>
      <h2>{{ post.title }}</h2>
      {% if post.kind == 'image' %}
        <img class="media" src="{{ url_for('media',filename=post.filename) }}"
        alt="{{ post.title }}">
      {% else %}
        <video id="player" class="media" controls playsinline preload="metadata"
        src="{{ url_for('media',filename=post.filename) }}"></video>
        <div class="row" style="margin-top:10px">
          <button type="button" class="secondary" onclick="skip(-10)">⏪ -10 detik</button>
          <button type="button" onclick="skip(10)">⏩ +10 detik</button>
        </div>
        <script>
        function skip(n) {
          const v = document.getElementById('player');
          if (v) {
            const end = Number.isFinite(v.duration) ? v.duration : Infinity;
            v.currentTime = Math.max(0, Math.min(end, v.currentTime + n));
          }
        }
        </script>
      {% endif %}
      <p><a href="{{ url_for('media',filename=post.filename) }}" download>
      ⬇ Download file</a></p>
      {% if user and user.id == post.user_id %}
      <form method="post" action="{{ url_for('delete_post',pid=post.id) }}"
      onsubmit="return confirm('Hapus postingan ini?')">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button class="danger">🗑️ Hapus postingan saya</button>
      </form>
      {% endif %}
    </div>

    <div class="card">
      <h3>💬 Komentar ({{ comments|length }})</h3>
      {% if user %}
      <form method="post">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <textarea name="message" rows="3" maxlength="1000"
        placeholder="Tulis komentar..."></textarea>
        <p>Pilih stiker:</p>
        <div class="stickers">
          {% for s in stickers %}
          <button type="button" onclick="pick(this.dataset.sticker)"
          data-sticker="{{ s }}">{{ s }}</button>
          {% endfor %}
        </div>
        <input type="hidden" name="sticker" id="sticker">
        <p id="selected" class="muted">Belum memilih stiker.</p>
        <button>Kirim komentar</button>
        <button type="button" class="secondary" onclick="pick('')">Batal stiker</button>
      </form>
      <script>
      function pick(s) {
        document.getElementById('sticker').value = s;
        document.getElementById('selected').textContent =
          s ? 'Stiker dipilih: ' + s : 'Stiker dibatalkan.';
      }
      </script>
      {% else %}
      <p><a href="{{ url_for('login') }}">Login</a> untuk komentar dan stiker.</p>
      {% endif %}

      {% for c in comments %}
      <div class="comment">
        <strong>{{ c.username }}</strong>
        <span class="muted">{{ c.created }}</span>
        {% if c.message %}<p style="white-space:pre-wrap">{{ c.message }}</p>{% endif %}
        {% if c.sticker %}<div style="font-size:38px">{{ c.sticker }}</div>{% endif %}
        {% if user and user.id == c.user_id %}
        <form method="post">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
          <input type="hidden" name="action" value="delete_comment">
          <input type="hidden" name="cid" value="{{ c.id }}">
          <button class="danger">Hapus komentar saya</button>
        </form>
        {% endif %}
      </div>
      {% else %}<p class="muted">Belum ada komentar.</p>{% endfor %}
    </div>
    """
    return page("Postingan", content, post=post, comments=comments,
                stickers=STICKERS)

@app.route("/delete/<int:pid>", methods=["POST"])
@login_required
def delete_post(pid):
    db = connect_db()
    post = db.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not post:
        db.close()
        abort(404)
    if post["user_id"] != session["uid"]:
        db.close()
        abort(403)

    db.execute("DELETE FROM comments WHERE post_id=?", (pid,))
    db.execute("DELETE FROM posts WHERE id=?", (pid,))
    db.commit()
    db.close()

    filepath = os.path.join(UPLOADS, post["filename"])
    if os.path.isfile(filepath):
        os.remove(filepath)
    flash("Postingan berhasil dihapus.")
    return redirect(url_for("home"))

@app.errorhandler(413)
def file_too_large(error):
    return "File terlalu besar. Batas upload 500 MB.", 413

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
