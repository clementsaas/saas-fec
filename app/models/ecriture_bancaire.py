from app.models import db


class EcritureBancaire(db.Model):
    """Table des écritures bancaires extraites des FEC (comptes 512*)"""
    __tablename__ = 'ecritures_bancaires'

    id = db.Column(db.Integer, primary_key=True)

    # Les 18 champs du FEC
    journal_code = db.Column(db.String(10), nullable=False)
    journal_lib = db.Column(db.String(100), nullable=False)
    ecriture_num = db.Column(db.String(20), nullable=False)
    ecriture_date = db.Column(db.Date, nullable=False)
    compte_num = db.Column(db.String(20), nullable=False)
    compte_lib = db.Column(db.String(200), nullable=False)
    comp_aux_num = db.Column(db.String(20), nullable=True)
    comp_aux_lib = db.Column(db.String(200), nullable=True)
    piece_ref = db.Column(db.String(30), nullable=True)
    piece_date = db.Column(db.Date, nullable=True)
    ecriture_lib = db.Column(db.Text, nullable=False)
    debit = db.Column(db.Numeric(15, 2), nullable=True)
    credit = db.Column(db.Numeric(15, 2), nullable=True)
    ecriture_let = db.Column(db.String(10), nullable=True)
    date_let = db.Column(db.Date, nullable=True)
    valid_date = db.Column(db.Date, nullable=True)
    montant_devise = db.Column(db.Numeric(15, 2), nullable=True)
    id_devise = db.Column(db.String(3), nullable=True)

    # Champs calculés pour les règles
    compte_final = db.Column(db.String(20), nullable=False)
    libelle_final = db.Column(db.String(200), nullable=False)
    montant = db.Column(db.Numeric(15, 2), nullable=False)
    sens = db.Column(db.String(1), nullable=False)  # 'D' ou 'C'

    # Lien vers le fichier FEC
    fec_file_id = db.Column(db.Integer, db.ForeignKey('fec_files.id'), nullable=False)

    # Champs pour la contrepartie (ajoutés pour la logique métier)
    compte_contrepartie = db.Column(db.String(20), nullable=True)
    libelle_contrepartie = db.Column(db.String(200), nullable=True)

    def __repr__(self):
        return f'<EcritureBancaire {self.ecriture_num} - {self.montant}€>'