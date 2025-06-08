from app.models import db
from datetime import datetime


class Societe(db.Model):
    """Table des sociétés/clients/entités comptables"""
    __tablename__ = 'societes'

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(200), nullable=False)
    siret = db.Column(db.String(14), nullable=True)
    date_debut_exercice = db.Column(db.Date, nullable=True)
    date_fin_exercice = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Lien vers l'organisation
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)

    def __repr__(self):
        return f'<Societe {self.nom}>'