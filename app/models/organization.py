from app.models import db
from datetime import datetime


class Organization(db.Model):
    """Table des organisations (cabinets, entreprises, solo)"""
    __tablename__ = 'organizations'

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(200), nullable=False)
    type_org = db.Column(db.String(20), nullable=False)  # 'cabinet', 'entreprise', 'solo'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Organization {self.nom}>'