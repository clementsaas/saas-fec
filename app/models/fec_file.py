from app.models import db
from datetime import datetime


class FecFile(db.Model):
    """Table des fichiers FEC importés (max 3 par société)"""
    __tablename__ = 'fec_files'

    id = db.Column(db.Integer, primary_key=True)
    nom_fichier = db.Column(db.String(255), nullable=False)
    nom_original = db.Column(db.String(255), nullable=False)
    taille_fichier = db.Column(db.BigInteger, nullable=False)  # En octets
    nb_lignes_total = db.Column(db.Integer, nullable=False)
    nb_lignes_bancaires = db.Column(db.Integer, nullable=False)  # Lignes 512*
    date_import = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    # Métadonnées du traitement
    encodage_detecte = db.Column(db.String(50), nullable=True)
    separateur_detecte = db.Column(db.String(5), nullable=True)

    # Lien vers la société
    societe_id = db.Column(db.Integer, db.ForeignKey('societes.id'), nullable=False)

    def __repr__(self):
        return f'<FecFile {self.nom_original}>'