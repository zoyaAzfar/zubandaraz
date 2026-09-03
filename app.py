import os
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


ADMIN_PASSWORD = os.environ.get(
    "ADMIN_PASSWORD",
    "default_admin_password"
)

users = {
    "admin": generate_password_hash(ADMIN_PASSWORD),
    "moderator": generate_password_hash(ADMIN_PASSWORD)
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



# with app.app_context():
#     db.create_all()


def make_unique_slug(word):
    base = slugify(word)
    slug = base
    i = 1

    while Entry.query.filter_by(slug=slug).first():
        i += 1
        slug = f"{base}-{i}"

    return slug


@app.route("/")
def home():
    count = Entry.query.count()
    return render_template(
        "index.html",
        submission_count=count
    )


@app.route("/submit")
def submit_page():
    return render_template("submit.html")


@app.route("/about")
def about_page():
    return render_template("aboutus.html")


@app.route("/browse")
def browse():
    entries = (
        Entry.query
        .filter_by(status="approved")
        .order_by(Entry.word)
        .all()
    )

    return render_template(
        "browse.html",
        entries=entries
    )

@app.route('/entry/<slug>')
def entry_detail(slug):
    # Use ORM to fetch the entry, just like your edit_entry route does!
    entry = Entry.query.filter_by(slug=slug, status="approved").first_or_404()

    # Fetch approved stories for this entry using raw SQL via SQLAlchemy
    stories = db.session.execute(
        text("SELECT * FROM stories WHERE entry_id = :entry_id AND is_approved = 1 ORDER BY created_at DESC"), 
        {"entry_id": entry.id}
    ).fetchall()

    return render_template('entry.html', entry=entry, stories=stories)


@app.route('/entry/<slug>/submit-story', methods=['GET', 'POST'])
def submit_story(slug):
    # Fetch entry to make sure it exists
    entry = Entry.query.filter_by(slug=slug, status="approved").first_or_404()
    
    if request.method == 'POST':
        content = request.form['content']
        submitted_by = request.form['submitted_by']
        
        # Insert the new story using raw SQL via SQLAlchemy
        db.session.execute(
            text("INSERT INTO stories (entry_id, content, submitted_by) VALUES (:entry_id, :content, :submitted_by)"),
            {"entry_id": entry.id, "content": content, "submitted_by": submitted_by}
        )
        db.session.commit()
        
        # Redirect back to the entry page
        return redirect(url_for('entry', slug=slug, story_submitted=True))
        
    return render_template('submit-story.html', entry=entry)
    
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

    origin = request.form.get("origin") or None
    dialect = request.form.get("dialect") or None
    source = request.form.get("source") or None

    # Basic input validation
    if (
        not word
        or not language
        or not story
        or len(word) > 100
        or len(story) > 2000
    ):
        return "Invalid input length", 400

    entry = Entry(
        word=word,
        slug=make_unique_slug(word),
        story=story,
        language=language,

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

        status="pending"
    )

    db.session.add(entry)
    db.session.commit()

    return redirect("/browse")


@app.route("/admin")
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

    # NEW: Fetch pending stories using SQLAlchemy's text() wrapper
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

@app.route("/approve_story/<int:story_id>", methods=["POST"])
@auth.login_required
def approve_story(story_id):
    db.session.execute(
        text("UPDATE stories SET is_approved = 1 WHERE id = :id"), 
        {"id": story_id}
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
    "/approve/<int:id>",
    methods=["POST"]
)
@auth.login_required
def approve(id):

    entry = Entry.query.get_or_404(id)

    entry.origin = (
        request.form.get("origin")
        or None
    )

    entry.dialect = (
        request.form.get("dialect")
        or None
    )

    entry.source = (
        request.form.get("source")
        or None
    )

    entry.status = "approved"

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
        "language",
        "literal_definition",
        "etymology",
        "story",
        "origin",
        "dialect",
        "source"
    ]

    for field in editable_fields:

        value = getattr(edit, field)

        if value is not None:
            setattr(entry, field, value)

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



if __name__ == "__main__":
    app.run(debug=False)
