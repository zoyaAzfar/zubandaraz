import os
import random
import secrets
from datetime import date

from flask import Flask, render_template, request, redirect, make_response, url_for, abort
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text
from models import db, Entry, EntryEdit
from slugify import slugify

app = Flask(__name__)

db_url = os.environ.get("TURSO_DATABASE_URL")
auth_token = os.environ.get("TURSO_AUTH_TOKEN")

if db_url and db_url.startswith("libsql://"):
    stripped = db_url.replace("libsql://", "", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"sqlite+libsql://{stripped}?secure=true"
    )

    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {
            "auth_token": auth_token
        }
    }

else:
    fallback = os.environ.get(
        "DATABASE_URL",
        "sqlite:///dictionary.db"
    )

    if fallback.startswith("postgres://"):
        fallback = fallback.replace(
            "postgres://",
            "postgresql://",
            1
        )

    app.config["SQLALCHEMY_DATABASE_URI"] = fallback


db.init_app(app)


auth = HTTPBasicAuth()


@auth.error_handler
def unauthorized():
    response = make_response(
        "Unauthorized Access",
        401
    )
    response.headers["WWW-Authenticate"] = (
        'Basic realm="Login Required"'
    )
    return response


# FIX: no more shared hardcoded fallback password. If the env var isn't set
# we generate a one-time password and log it loudly instead of silently
# booting with a value that's now sitting in this file (and possibly a
# public repo). Admin and moderator also get independent passwords.
def _resolve_password(env_var):
    value = os.environ.get(env_var)
    if value:
        return value
    generated = secrets.token_urlsafe(16)
    app.logger.warning(
        "%s is not set — generated a one-time password for this run: %s "
        "(set %s in your environment before deploying).",
        env_var, generated, env_var
    )
    return generated


ADMIN_PASSWORD = _resolve_password("ADMIN_PASSWORD")
MODERATOR_PASSWORD = _resolve_password("MODERATOR_PASSWORD")

users = {
    "admin": generate_password_hash(ADMIN_PASSWORD),
    "moderator": generate_password_hash(MODERATOR_PASSWORD)
}


@auth.verify_password
def verify_password(username, password):
    if (
        username in users
        and check_password_hash(
            users.get(username),
            password
        )
    ):
        return username


#with app.app_context():
#    db.create_all()

def make_unique_slug(word, exclude_entry_id=None):
    base = slugify(word, allow_unicode=True)

    if not base:
        base = word.strip()

    slug = base
    i = 1

    def taken(candidate):
        q = Entry.query.filter_by(slug=candidate)
        if exclude_entry_id is not None:
            q = q.filter(Entry.id != exclude_entry_id)
        return q.first() is not None

    while taken(slug):
        i += 1
        slug = f"{base}-{i}"

    return slug

# Best-effort script detection, so a word renders in the right font and
# direction without needing a dedicated "script" column per entry — useful
# since e.g. Punjabi can show up in either Gurmukhi (LTR) or Shahmukhi
# (Arabic script, RTL) depending on who submitted it.
_SCRIPT_RANGES = [
    ("arabic", 0x0600, 0x06FF, True),
    ("arabic", 0x0750, 0x077F, True),
    ("arabic", 0xFB50, 0xFDFF, True),
    ("arabic", 0xFE70, 0xFEFF, True),
    ("devanagari", 0x0900, 0x097F, False),
    ("bengali", 0x0980, 0x09FF, False),
    ("gurmukhi", 0x0A00, 0x0A7F, False),
    ("tamil", 0x0B80, 0x0BFF, False),
    ("telugu", 0x0C00, 0x0C7F, False)
]


def detect_script(word):
    if not word:
        return "latin", False
    for ch in word:
        cp = ord(ch)
        for name, lo, hi, rtl in _SCRIPT_RANGES:
            if lo <= cp <= hi:
                return name, rtl
    return "latin", False


app.jinja_env.globals["detect_script"] = detect_script


def pick_word_of_day(approved_entries):
    """Deterministic per-day pick so it doesn't change on every refresh."""
    if not approved_entries:
        return None
    rng = random.Random(date.today().isoformat())
    return rng.choice(approved_entries)


@app.route("/")
def home():
    count = Entry.query.count()
    approved = Entry.query.filter_by(status="approved").all()

    word_of_day = pick_word_of_day(approved)

    pool = [e for e in approved if not word_of_day or e.id != word_of_day.id]
    if len(pool) <= 3:
        preview_entries = pool
    else:
        preview_entries = random.Random(date.today().isoformat() + "-preview").sample(pool, 3)

    story_count = 0
    if word_of_day:
        story_count = db.session.execute(
            text("SELECT COUNT(*) FROM stories WHERE entry_id = :entry_id AND is_approved = 1"),
            {"entry_id": word_of_day.id}
        ).scalar()

    return render_template(
        "index.html",
        submission_count=count,
        word_of_day=word_of_day,
        word_of_day_story_count=story_count,
        entries=preview_entries,
    )


@app.route("/submit")
def submit_page():
    return render_template("submit.html")


@app.route("/about")
def about_page():
    return render_template("aboutus.html")


@app.route("/mod-policy")
def mod_policy():
    return render_template("mod-policy.html")

@app.route("/browse")
def browse():
    q = (request.args.get("q") or "").strip()
    language = (request.args.get("language") or "").strip()
 
    query = Entry.query.filter_by(status="approved")
    if language:
        query = query.filter(Entry.language == language)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Entry.word.ilike(like),
                Entry.transliteration.ilike(like),
                Entry.literal_definition.ilike(like),
                Entry.story.ilike(like),
            )
        )
 
    entries = query.order_by(Entry.word).all()
 
    story_counts = dict(db.session.execute(
        text("SELECT entry_id, COUNT(*) FROM stories WHERE is_approved = 1 GROUP BY entry_id")
    ).all())
 
    return render_template(
        "browse.html",
        entries=entries,
        q=q,
        language=language,
        story_counts=story_counts,
    )
 
 


@app.route('/entry/<slug>')
def entry_detail(slug):
    entry = Entry.query.filter_by(slug=slug, status="approved").first_or_404()

    stories = db.session.execute(
        text("SELECT * FROM stories WHERE entry_id = :entry_id AND is_approved = 1 ORDER BY created_at DESC"),
        {"entry_id": entry.id}
    ).fetchall()

    return render_template('entry.html', entry=entry, stories=stories)


@app.route('/entry/<slug>/submit-story', methods=['GET', 'POST'])
def submit_story(slug):
    entry = Entry.query.filter_by(slug=slug, status="approved").first_or_404()

    if request.method == 'POST':
        content = (request.form.get('content') or "").strip()
        submitted_by = request.form.get('submitted_by') or None  # blank = anonymous

        # FIX: no validation at all before — an empty or absurdly long
        # story could be inserted.
        if not content or len(content) > 2000:
            return "Invalid input length", 400

        # FIX: is_approved was left out of this INSERT entirely, so new
        # stories landed as NULL. The admin queue below filters on
        # "is_approved = 0", and NULL never matches that — new
        # submissions were invisible to moderators. Setting it explicitly
        # here puts them back in the queue.
        db.session.execute(
            text("""
                INSERT INTO stories (entry_id, content, submitted_by, is_approved)
                VALUES (:entry_id, :content, :submitted_by, 0)
            """),
            {"entry_id": entry.id, "content": content, "submitted_by": submitted_by}
        )
        db.session.commit()

        return redirect(url_for('entry_detail', slug=slug, story_submitted=True))

    return render_template('submit-story.html', entry=entry)

@app.route("/approve_story/<int:story_id>", methods=["POST"])
@auth.login_required
def approve_story(story_id):
    db.session.execute(
        text("UPDATE stories SET is_approved = 1 WHERE id = :id"),
        {"id": story_id}
    )
    db.session.commit()
    return redirect("/admin")

@app.route(
    "/entry/<slug>/edit",
    methods=["GET", "POST"]
)
def edit_entry(slug):

    entry = (
        Entry.query
        .filter_by(
            slug=slug,
            status="approved"
        )
        .first_or_404()
    )

    if request.method == "POST":

        edit = EntryEdit(
            entry_id=entry.id,

            word=request.form.get("word") or None,
            transliteration=request.form.get("transliteration") or None,
            language=request.form.get("language") or None,
            literal_definition=(
                request.form.get("literal_definition")
                or None
            ),
            etymology=(
                request.form.get("etymology")
                or None
            ),
            story=request.form.get("story") or None,
            origin=request.form.get("origin") or None,
            dialect=request.form.get("dialect") or None,
            source=request.form.get("source") or None,
            submitted_by=(
                request.form.get("submitted_by")
                or None
            ),

            status="pending"
        )

        db.session.add(edit)
        db.session.commit()

        return redirect(
            f"/entry/{slug}?edit_submitted=1"
        )

    return render_template(
        "edit_entry.html",
        entry=entry
    )



@app.route("/submit", methods=["POST"])
def submit():

    word = request.form.get("word")
    language = request.form.get("language")
    story = request.form.get("story")

    transliteration = request.form.get("transliteration") or None
    origin = request.form.get("origin") or None
    dialect = request.form.get("dialect") or None
    source = request.form.get("source") or None
    # FIX: this was never being read from the form at all, which is why
    # approve() below had nothing to credit and fell back to a hardcoded
    # placeholder name for every single entry.
    submitted_by = request.form.get("submitted_by") or None

    # Basic input validation
    if (
        not word
        or not language
        or len(word) > 100
        or len(story or "") > 2000
    ):
        return "Invalid input length", 400

    entry = Entry(
        word=word,
        slug=make_unique_slug(word),
        story=story,
        language=language,
        transliteration=transliteration,

        literal_definition=(
            request.form.get("literal_definition")
            or None
        ),

        etymology=(
            request.form.get("etymology")
            or None
        ),

        origin=origin,
        dialect=dialect,
        source=source,
        submitted_by=submitted_by,

        status="pending"
    )

    db.session.add(entry)
    db.session.commit()

    return redirect("/browse")

@app.route("/admin")
@auth.login_required
def admin():

    pending_entries = (
        Entry.query
        .filter_by(status="pending")
        .order_by(Entry.created_at)
        .all()
    )

    pending_edits = (
        EntryEdit.query
        .filter_by(status="pending")
        .order_by(EntryEdit.created_at)
        .all()
    )

    pending_stories = db.session.execute(text("""
        SELECT stories.*, entries.word 
        FROM stories 
        JOIN entries ON stories.entry_id = entries.id 
        WHERE stories.is_approved = 0
    """)).fetchall()

    return render_template(
        "admin.html",
        pending=pending_entries,
        pending_edits=pending_edits,
        pending_stories=pending_stories
    )

@app.route("/approve/<int:id>", methods=["POST"])
@auth.login_required
def approve(id):
    entry = Entry.query.get_or_404(id)

    entry.language = request.form.get("language") or entry.language
    entry.etymology = request.form.get("etymology") or None
    entry.origin = request.form.get("origin") or None
    entry.dialect = request.form.get("dialect") or None
    entry.source = request.form.get("source") or None
    entry.status = "approved"

    if entry.story:
        # FIX: this used to hardcode submitted_by to the literal string
        # 'Original Submitter' for every entry, regardless of whether the
        # person who submitted it asked to be credited or to stay
        # anonymous. It now uses whatever they actually chose, and only
        # falls back to "Anonymous" (matching how every later story is
        # labeled) when they left it blank.
        db.session.execute(
            text("""
                INSERT INTO stories (entry_id, content, submitted_by, is_approved) 
                VALUES (:entry_id, :content, :submitted_by, 1)
            """),
            {
                "entry_id": entry.id,
                "content": entry.story,
                "submitted_by": entry.submitted_by or "Anonymous",
            }
        )

    db.session.commit()

    return redirect("/admin")

@app.route("/reject_story/<int:story_id>", methods=["POST"])
@auth.login_required
def reject_story(story_id):
    db.session.execute(
        text("DELETE FROM stories WHERE id = :id"), 
        {"id": story_id}
    )
    db.session.commit()
    return redirect("/admin")
    

@app.route(
    "/delete/<int:id>",
    methods=["POST"]
)
@auth.login_required
def delete(id):

    entry = Entry.query.get_or_404(id)

    db.session.delete(entry)
    db.session.commit()

    return redirect("/admin")


@app.route(
    "/approve_edit/<int:id>",
    methods=["POST"]
)
@auth.login_required
def approve_edit(id):

    edit = EntryEdit.query.get_or_404(id)

    entry = edit.entry

    editable_fields = [
        "word",
        "transliteration",
        "language",
        "literal_definition",
        "etymology",
        "story",
        "origin",
        "dialect",
        "source"
    ]

    old_word = entry.word

    for field in editable_fields:

        value = getattr(edit, field)

        if value is not None:
            setattr(entry, field, value)

    # FIX: an approved word-text edit was never reflected in the URL —
    # the slug stayed whatever it was at creation, silently drifting out
    # of sync with the displayed word.
    if entry.word != old_word:
        entry.slug = make_unique_slug(entry.word, exclude_entry_id=entry.id)

    # Mark the edit as approved
    edit.status = "approved"

    db.session.commit()

    return redirect("/admin")


@app.route(
    "/reject_edit/<int:id>",
    methods=["POST"]
)
@auth.login_required
def reject_edit(id):

    edit = EntryEdit.query.get_or_404(id)

    edit.status = "rejected"

    db.session.commit()

    return redirect("/admin")

@app.route("/setup-db-secret")
def setup_db():
    # This manually creates the tables in Turso
    with app.app_context():
        db.create_all()
    return "dbs made."

if __name__ == "__main__":
    app.run(debug=False)
