from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(100), nullable=False)
    story = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default="pending")
    
    # New optional metadata fields
    origin = db.Column(db.String(150), nullable=True)
    dialect = db.Column(db.String(100), nullable=True)
    source = db.Column(db.String(250), nullable=True)
