from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Entry(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    word = db.Column(db.String(100))

    story = db.Column(db.Text)

    language = db.Column (db.String(100))

    status = db.Column(db.String(20), default="pending")
