import os, sqlite3, secrets
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(ROOT, "bizbridge.db"))
UPLOAD_DIR = os.environ.get("UPLOAD_FOLDER", os.path.join(ROOT, "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)
app = Flask(__name__, template_folder=".")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "100")) * 1024 * 1024
ALLOWED = {"jpg","jpeg","png","gif","webp","mp4","webm","mov","m4v"}

def connect():
    c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def stamp(): return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, bio TEXT DEFAULT '', created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, caption TEXT DEFAULT '', filename TEXT NOT NULL, kind TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS likes(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, PRIMARY KEY(user_id,post_id));
        CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, body TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS follows(follower INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, following INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, PRIMARY KEY(follower,following), CHECK(follower!=following));
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, sender INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, recipient INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, body TEXT NOT NULL, created TEXT NOT NULL, is_read INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS blogs(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, title TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL);
        """)
init_db()

def user():
    if not session.get("uid"): return None
    with connect() as c: return c.execute("SELECT id,username,email,bio,created FROM users WHERE id=?", (session["uid"],)).fetchone()

@app.context_processor
def context(): return {"me": user()}

def login_required(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        if not session.get("uid"):
            flash("ఈ ఫీచర్ కోసం ముందుగా లాగిన్ అవ్వండి.", "info")
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapped

@app.route("/")
def home():
    q=request.args.get("q","").strip(); uid=session.get("uid",-1)
    with connect() as c:
        sql="""SELECT p.*,u.username,(SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) likes,
        (SELECT COUNT(*) FROM comments cm WHERE cm.post_id=p.id) comments,
        EXISTS(SELECT 1 FROM likes l WHERE l.post_id=p.id AND l.user_id=?) liked
        FROM posts p JOIN users u ON u.id=p.user_id"""
        args=[uid]
        if q: sql+=" WHERE p.caption LIKE ? OR u.username LIKE ?"; args += [f"%{q}%",f"%{q}%"]
        posts=c.execute(sql+" ORDER BY p.id DESC LIMIT 80",args).fetchall()
        blogs=c.execute("SELECT b.*,u.username FROM blogs b JOIN users u ON u.id=b.user_id ORDER BY b.id DESC LIMIT 5").fetchall()
        creators=c.execute("SELECT id,username,(SELECT COUNT(*) FROM follows f WHERE f.following=u.id) followers FROM users u ORDER BY id DESC LIMIT 8").fetchall()
    return render_template("home.html",posts=posts,blogs=blogs,creators=creators,q=q)

@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="POST":
        name=request.form.get("username","").strip(); email=request.form.get("email","").strip().lower(); pw=request.form.get("password","")
        if len(name)<3 or len(name)>30 or not name.replace("_","").isalnum(): flash("Username 3–30 అక్షరాలు; letters, numbers, _ మాత్రమే.", "error")
        elif "@" not in email: flash("సరైన email ఇవ్వండి.", "error")
        elif len(pw)<8: flash("Password కనీసం 8 అక్షరాలు ఉండాలి.", "error")
        else:
            try:
                with connect() as c: cur=c.execute("INSERT INTO users(username,email,password,created) VALUES(?,?,?,?)",(name,email,generate_password_hash(pw),stamp()))
                session.clear(); session["uid"]=cur.lastrowid
                return redirect(url_for("home"))
            except sqlite3.IntegrityError: flash("ఈ username లేదా email ఇప్పటికే ఉంది.", "error")
    return render_template("auth.html",mode="register")

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        ident=request.form.get("identity","").strip().lower(); pw=request.form.get("password","")
        with connect() as c: u=c.execute("SELECT * FROM users WHERE lower(username)=? OR lower(email)=?",(ident,ident)).fetchone()
        if u and check_password_hash(u["password"],pw):
            session.clear(); session["uid"]=u["id"]; return redirect(url_for("home"))
        flash("లాగిన్ వివరాలు సరిపోలలేదు.", "error")
    return render_template("auth.html",mode="login")

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("home"))

@app.route("/upload",methods=["GET","POST"])
@login_required
def upload():
    if request.method=="POST":
        f=request.files.get("media"); caption=request.form.get("caption","").strip()[:1000]
        if not f or not f.filename: flash("ఫోటో లేదా వీడియో ఎంచుకోండి.", "error")
        elif "." not in f.filename or f.filename.rsplit(".",1)[1].lower() not in ALLOWED: flash("JPG, PNG, WEBP, MP4, WEBM, MOV మాత్రమే.", "error")
        else:
            ext=f.filename.rsplit(".",1)[1].lower(); name=secure_filename(f"{session['uid']}_{secrets.token_hex(10)}.{ext}")
            f.save(os.path.join(UPLOAD_DIR,name)); kind="video" if ext in {"mp4","webm","mov","m4v"} else "image"
            with connect() as c: c.execute("INSERT INTO posts(user_id,caption,filename,kind,created) VALUES(?,?,?,?,?)",(session["uid"],caption,name,kind,stamp()))
            flash("పోస్ట్ అప్లోడ్ అయింది!", "success"); return redirect(url_for("home"))
    return render_template("upload.html")

@app.route("/media/<path:name>")
def media(name): return send_from_directory(UPLOAD_DIR,name)

@app.route("/post/<int:pid>")
def post(pid):
    uid=session.get("uid",-1)
    with connect() as c:
        p=c.execute("""SELECT p.*,u.username,(SELECT COUNT(*) FROM likes WHERE post_id=p.id) likes,
        EXISTS(SELECT 1 FROM likes WHERE post_id=p.id AND user_id=?) liked FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id=?""",(uid,pid)).fetchone()
        if not p: abort(404)
        comments=c.execute("SELECT cm.*,u.username FROM comments cm JOIN users u ON u.id=cm.user_id WHERE post_id=? ORDER BY cm.id",(pid,)).fetchall()
    return render_template("post.html",p=p,comments=comments)

@app.route("/post/<int:pid>/like",methods=["POST"])
@login_required
def like(pid):
    with connect() as c:
        if not c.execute("SELECT id FROM posts WHERE id=?",(pid,)).fetchone(): abort(404)
        exists=c.execute("SELECT 1 FROM likes WHERE user_id=? AND post_id=?",(session["uid"],pid)).fetchone()
        if exists: c.execute("DELETE FROM likes WHERE user_id=? AND post_id=?",(session["uid"],pid))
        else: c.execute("INSERT INTO likes(user_id,post_id) VALUES(?,?)",(session["uid"],pid))
    return redirect(request.referrer or url_for("home"))

@app.route("/post/<int:pid>/comment",methods=["POST"])
@login_required
def comment(pid):
    body=request.form.get("body","").strip()
    if body and len(body)<=1000:
        with connect() as c:
            if not c.execute("SELECT id FROM posts WHERE id=?",(pid,)).fetchone(): abort(404)
            c.execute("INSERT INTO comments(user_id,post_id,body,created) VALUES(?,?,?,?)",(session["uid"],pid,body,stamp()))
    return redirect(url_for("post",pid=pid))

@app.route("/u/<username>")
def profile(username):
    uid=session.get("uid",-1)
    with connect() as c:
        u=c.execute("SELECT id,username,bio,created FROM users WHERE lower(username)=lower(?)",(username,)).fetchone()
        if not u: abort(404)
        followers=c.execute("SELECT COUNT(*) n FROM follows WHERE following=?",(u["id"],)).fetchone()["n"]
        following=c.execute("SELECT COUNT(*) n FROM follows WHERE follower=?",(u["id"],)).fetchone()["n"]
        is_following=bool(c.execute("SELECT 1 FROM follows WHERE follower=? AND following=?",(uid,u["id"])).fetchone()) if uid!=-1 else False
        posts=c.execute("SELECT * FROM posts WHERE user_id=? ORDER BY id DESC",(u["id"],)).fetchall()
        blogs=c.execute("SELECT * FROM blogs WHERE user_id=? ORDER BY id DESC",(u["id"],)).fetchall()
    return render_template("profile.html",u=u,followers=followers,following=following,is_following=is_following,posts=posts,blogs=blogs)

@app.route("/u/<username>/follow",methods=["POST"])
@login_required
def follow(username):
    with connect() as c:
        target=c.execute("SELECT id FROM users WHERE lower(username)=lower(?)",(username,)).fetchone()
        if not target: abort(404)
        if target["id"]!=session["uid"]:
            row=c.execute("SELECT 1 FROM follows WHERE follower=? AND following=?",(session["uid"],target["id"])).fetchone()
            if row: c.execute("DELETE FROM follows WHERE follower=? AND following=?",(session["uid"],target["id"]))
            else: c.execute("INSERT INTO follows(follower,following) VALUES(?,?)",(session["uid"],target["id"]))
    return redirect(url_for("profile",username=username))

@app.route("/blogs")
def blogs():
    with connect() as c: rows=c.execute("SELECT b.*,u.username FROM blogs b JOIN users u ON u.id=b.user_id ORDER BY b.id DESC").fetchall()
    return render_template("blogs.html",blogs=rows)

@app.route("/blogs/new",methods=["GET","POST"])
@login_required
def blog_new():
    if request.method=="POST":
        title=request.form.get("title","").strip()[:160]; body=request.form.get("body","").strip()[:20000]
        if title and body:
            with connect() as c: c.execute("INSERT INTO blogs(user_id,title,body,created) VALUES(?,?,?,?)",(session["uid"],title,body,stamp()))
            return redirect(url_for("blogs"))
        flash("శీర్షిక, విషయం రెండూ ఇవ్వండి.", "error")
    return render_template("blog_form.html")

@app.route("/blogs/<int:bid>")
def blog_detail(bid):
    with connect() as c: b=c.execute("SELECT b.*,u.username FROM blogs b JOIN users u ON u.id=b.user_id WHERE b.id=?",(bid,)).fetchone()
    if not b: abort(404)
    return render_template("blog_detail.html",b=b)

@app.route("/messages")
@login_required
def messages():
    uid=session["uid"]
    with connect() as c:
        contacts=c.execute("""SELECT u.id,u.username,(SELECT body FROM messages m WHERE (m.sender=u.id AND m.recipient=?) OR (m.sender=? AND m.recipient=u.id) ORDER BY m.id DESC LIMIT 1) last
        FROM users u WHERE u.id!=? ORDER BY u.username""",(uid,uid,uid)).fetchall()
    return render_template("messages.html",contacts=contacts)

@app.route("/messages/<username>",methods=["GET","POST"])
@login_required
def chat(username):
    uid=session["uid"]
    with connect() as c:
        other=c.execute("SELECT id,username FROM users WHERE lower(username)=lower(?)",(username,)).fetchone()
        if not other: abort(404)
        if other["id"]==uid: return redirect(url_for("messages"))
        if request.method=="POST":
            body=request.form.get("body","").strip()
            if body and len(body)<=2000:
                c.execute("INSERT INTO messages(sender,recipient,body,created) VALUES(?,?,?,?)",(uid,other["id"],body,stamp()))
                return redirect(url_for("chat",username=other["username"]))
        c.execute("UPDATE messages SET is_read=1 WHERE sender=? AND recipient=?",(other["id"],uid))
        thread=c.execute("""SELECT m.*,u.username sender_name FROM messages m JOIN users u ON u.id=m.sender
        WHERE (m.sender=? AND m.recipient=?) OR (m.sender=? AND m.recipient=?) ORDER BY m.id LIMIT 500""",(uid,other["id"],other["id"],uid)).fetchall()
    return render_template("chat.html",other=other,thread=thread)

@app.errorhandler(413)
def too_large(e): return "ఫైల్ పరిమాణం ఎక్కువ. 100 MB లోపు ఫైల్ ఎంచుకోండి.",413
@app.errorhandler(404)
def missing(e): return render_template("404.html"),404

if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT","5000")))
