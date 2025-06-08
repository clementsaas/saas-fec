from app.models import db
from datetime import datetime


class RegleAffectation(db.Model):
    """Table des règles d'affectation créées par les utilisateurs"""
    __tablename__ = 'regles_affectation'

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(200), nullable=False)

    # Critères de la règle (JSON pour flexibilité)
    mots_cles = db.Column(db.JSON, nullable=False)  # ["mot1", "mot2"]
    criteres_montant = db.Column(db.JSON, nullable=True)  # {"operateur": ">=", "valeur": 100.0}
    journal_code = db.Column(db.String(10), nullable=True)  # Optionnel

    # Compte de destination
    compte_destination = db.Column(db.String(20), nullable=False)
    libelle_destination = db.Column(db.String(200), nullable=False)

    # Statistiques de couverture (calculées automatiquement)
    nb_transactions_couvertes = db.Column(db.Integer, default=0)
    pourcentage_couverture_compte = db.Column(db.Numeric(5, 2), default=0.0)
    pourcentage_couverture_total = db.Column(db.Numeric(5, 2), default=0.0)

    # Métadonnées
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Lien vers la société
    societe_id = db.Column(db.Integer, db.ForeignKey('societes.id'), nullable=False)

    def __repr__(self):
        return f'<RegleAffectation {self.nom}>'