import os
from flask import Flask, render_template, request, redirect, make_response
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Entry
from slugify import slugify

app = Flask(__name__)

db_url = os.environ.get("TURSO_DATABASE_URL")   
auth_token = os.environ.get("TURSO_AUTH_TOKEN")

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite+{db_url.replace('libsql://', 'libsql://')}?authToken={auth_token}&secure=true"

db.init_app(app)


auth = HTTPBasicAuth()

@auth.error_handler
def unauthorized():
    response = make_response("Unauthorized Access", 401)
    response.headers["WWW-Authenticate"] = 'Basic realm="Login Required"'
    return response

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "default_admin_password")

# PROBLEM AREA WILL BE HERE PROBABLY
users = {
    "admin": generate_password_hash(ADMIN_PASSWORD),
    "moderator": generate_password_hash(ADMIN_PASSWORD)
}

def make_unique_slug(word):
    base = slugify(word)
    slug = base
    i = 1
    while Entry.query.filter_by(slug=slug).first():
        i += 1
        slug = f"{base}-{i}"
    return slug

@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username

with app.app_context():
    db.create_all()

@app.route("/")
def home():
    count = Entry.query.count()
    return render_template("index.html", submission_count=count)

@app.route("/submit")
def submit_page():
    return render_template("submit.html")

@app.route("/about")
def about_page():
    return render_template("aboutus.html")


@app.route("/entry/<slug>")
def entry_detail(slug):
    entry = Entry.query.filter_by(slug=slug, status="approved").first_or_404()
    return render_template("entry.html", entry=entry)

@app.route("/entry/<slug>/edit", methods=["GET", "POST"])
def edit_entry(slug):
    entry = Entry.query.filter_by(slug=slug, status="approved").first_or_404()

    if request.method == "POST":
        edit = EntryEdit(
            entry_id=entry.id,
            word=request.form.get("word") or None,
            language=request.form.get("language") or None,
            literal_definition=request.form.get("literal_definition") or None,
            etymology=request.form.get("etymology") or None,
            story=request.form.get("story") or None,
            origin=request.form.get("origin") or None,
            dialect=request.form.get("dialect") or None,
            source=request.form.get("source") or None,
            submitted_by=request.form.get("submitted_by") or None,
            status="pending",
        )
        db.session.add(edit)
        db.session.commit()
        return redirect(f"/entry/{slug}?edit_submitted=1")

    return render_template("edit_entry.html", entry=entry)

@app.route("/admin")
@auth.login_required
def admin():
    pending_entries = Entry.query.filter_by(status="pending").all()
    pending_edits = EntryEdit.query.filter_by(status="pending").all()
    return render_template("admin.html", pending=pending_entries, pending_edits=pending_edits)

@app.route("/approve_edit/<int:id>", methods=["POST"])
@auth.login_required
def approve_edit(id):
    edit = EntryEdit.query.get_or_404(id)
    entry = edit.entry

    # Only overwrite fields the editor actually changed
    for field in ["word", "language", "literal_definition", "etymology",
                  "story", "origin", "dialect", "source"]:
        val = getattr(edit, field)
        if val is not None:
            setattr(entry, field, val)

    edit.status = "approved"
    db.session.commit()
    return redirect("/admin")

@app.route("/reject_edit/<int:id>", methods=["POST"])
@auth.login_required
def reject_edit(id):
    edit = EntryEdit.query.get_or_404(id)
    edit.status = "rejected"
    db.session.commit()
    return redirect("/admin")

@app.route("/submit", methods=["POST"])
def submit():
    word = request.form.get("word")
    language = request.form.get("language")
    story = request.form.get("story")
    
    # Optional fields from user input
    origin = request.form.get("origin") or None
    dialect = request.form.get("dialect") or None
    source = request.form.get("source") or None

    if not word or not story or len(word) > 100 or len(story) > 2000:
        return "Invalid input length", 400

    entry = Entry(
        word=word,
        slug=make_unique_slug(word),
        story=story,
        language=language,
        literal_definition=request.form.get("literal_definition") or None,
        etymology=request.form.get("etymology") or None,
        origin=origin,
        dialect=dialect,
        source=source,
        status="pending"
    )

    db.session.add(entry)
    db.session.commit()

    return redirect("/browse")

@app.route("/browse")
def browse():
    entries = Entry.query.filter_by(status="approved").all()
    return render_template("browse.html", entries=entries)

if __name__ == "__main__":
    app.run(debug=False)
