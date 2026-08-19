import os
from flask import Flask, render_template, request, redirect, make_response
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Entry

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///dictionary.db"

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

# FIX: Renamed function from submit_page to about_page
@app.route("/about")
def about_page():
    return render_template("aboutus.html")

@app.route("/admin")
@auth.login_required
def admin():
    pending = Entry.query.filter_by(status="pending").all()
    return render_template("admin.html", pending=pending)

# Updated Approve Action
@app.route("/approve/<int:id>", methods=["POST"])
@auth.login_required
def approve(id):
    entry = Entry.query.get_or_404(id)
    
    # Grab the manual/edited inputs from the admin form
    origin = request.form.get("origin")
    dialect = request.form.get("dialect")
    source = request.form.get("source")

    # Update fields (save None/null if left blank)
    entry.origin = origin.strip() if origin and origin.strip() else None
    entry.dialect = dialect.strip() if dialect and dialect.strip() else None
    entry.source = source.strip() if source and source.strip() else None

    # Mark as approved and commit
    entry.status = "approved"
    db.session.commit()

    return redirect("/admin")

@app.route("/delete/<int:id>", methods=["POST"])
@auth.login_required
def delete(id):
    entry = Entry.query.get_or_404(id)
    db.session.delete(entry)
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
        story=story,
        language=language,
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
