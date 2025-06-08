import pandas as pd
import chardet
import os
from datetime import datetime
from app.models import db
from app.models.fec_file import FecFile
from app.models.ecriture_bancaire import EcritureBancaire


class FecProcessor:
    """Service de traitement des fichiers FEC"""

    def __init__(self):
        self.required_columns = [
            'JournalCode', 'JournalLib', 'EcritureNum', 'EcritureDate',
            'CompteNum', 'CompteLib', 'CompAuxNum', 'CompAuxLib',
            'PieceRef', 'PieceDate', 'EcritureLib', 'Debit', 'Credit',
            'EcritureLet', 'DateLet', 'ValidDate', 'Montantdevise', 'Idevise'
        ]

    def process_fec_file(self, file_path, original_filename, societe_id):
        """
        Traite un fichier FEC complet :
        1. Détecte l'encodage et le séparateur
        2. Valide le format
        3. Extrait les écritures bancaires (512*)
        4. Sauvegarde en base
        """
        try:
            # 1. Détection de l'encodage
            encoding = self._detect_encoding(file_path)
            print(f"Encodage détecté: {encoding}")

            # 2. Détection du séparateur
            separator = self._detect_separator(file_path, encoding)
            print(f"Séparateur détecté: {repr(separator)}")

            # 3. Lecture du fichier
            df = pd.read_csv(
                file_path,
                encoding=encoding,
                sep=separator,
                dtype=str,  # Tout en string pour l'instant
                keep_default_na=False
            )

            print(f"Fichier lu: {len(df)} lignes, {len(df.columns)} colonnes")

            # 4. Validation du format
            validation_result = self._validate_fec_format(df)
            if not validation_result['valid']:
                return {
                    'success': False,
                    'error': validation_result['error']
                }

            # 5. Extraction des écritures bancaires (512*)
            ecritures_bancaires = self._extract_ecritures_bancaires(df)
            print(f"Écritures bancaires extraites: {len(ecritures_bancaires)}")

            if len(ecritures_bancaires) == 0:
                return {
                    'success': False,
                    'error': 'Aucune écriture bancaire (compte 512*) trouvée dans le fichier'
                }

            # 6. Création de l'enregistrement FecFile
            fec_file = FecFile(
                nom_fichier=f"fec_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                nom_original=original_filename,
                taille_fichier=os.path.getsize(file_path),
                nb_lignes_total=len(df),
                nb_lignes_bancaires=len(ecritures_bancaires),
                encodage_detecte=encoding,
                separateur_detecte=repr(separator),
                societe_id=societe_id
            )

            db.session.add(fec_file)
            db.session.flush()  # Pour récupérer l'ID

            # 7. Sauvegarde des écritures bancaires
            self._save_ecritures_bancaires(ecritures_bancaires, fec_file.id)

            return {
                'success': True,
                'fec_file_id': fec_file.id,
                'stats': {
                    'nb_lignes_total': len(df),
                    'nb_lignes_bancaires': len(ecritures_bancaires),
                    'encodage': encoding,
                    'separateur': repr(separator)
                }
            }

        except Exception as e:
            print(f"Erreur traitement FEC: {e}")
            return {
                'success': False,
                'error': f'Erreur de traitement: {str(e)}'
            }

    def _detect_encoding(self, file_path):
        """Détecte l'encodage du fichier"""
        with open(file_path, 'rb') as f:
            raw_data = f.read(10000)  # Lire les 10 premiers Ko

        result = chardet.detect(raw_data)
        encoding = result['encoding']

        # Mapping des encodages courants
        if encoding and 'iso-8859' in encoding.lower():
            return 'iso-8859-1'
        elif encoding and 'utf' in encoding.lower():
            return 'utf-8'
        else:
            return 'utf-8'  # Par défaut

    def _detect_separator(self, file_path, encoding):
        """Détecte le séparateur (virgule, point-virgule, tabulation)"""
        separators = [';', ',', '\t']

        with open(file_path, 'r', encoding=encoding) as f:
            first_line = f.readline()

        # Compter les occurrences de chaque séparateur
        sep_counts = {}
        for sep in separators:
            sep_counts[sep] = first_line.count(sep)

        # Prendre le séparateur le plus fréquent
        best_sep = max(sep_counts, key=sep_counts.get)

        # Vérifier que ça donne bien 18 colonnes
        if first_line.count(best_sep) >= 17:  # 18 colonnes = 17 séparateurs
            return best_sep

        return ';'  # Par défaut

    def _validate_fec_format(self, df):
        """Valide que le fichier a le bon format FEC"""
        if len(df.columns) < 18:
            return {
                'valid': False,
                'error': f'Format invalide: {len(df.columns)} colonnes trouvées, 18 attendues'
            }

        return {'valid': True}

    def _extract_ecritures_bancaires(self, df):
        """Extrait les écritures bancaires (comptes 512*)"""
        # Utiliser les noms de colonnes par index pour éviter les problèmes d'encodage
        df.columns = self.required_columns[:len(df.columns)]

        # Filtrer les lignes avec CompteNum commençant par 512
        mask = df['CompteNum'].str.startswith('512', na=False)
        ecritures_512 = df[mask].copy()

        return ecritures_512

    def _save_ecritures_bancaires(self, ecritures_df, fec_file_id):
        """Sauvegarde les écritures bancaires en base"""
        for _, row in ecritures_df.iterrows():
            # Calcul des champs finaux
            compte_final = row['CompAuxNum'] if row['CompAuxNum'] else row['CompteNum']
            libelle_final = row['CompAuxLib'] if row['CompAuxLib'] else row['CompteLib']

            # Calcul du montant et sens
            debit = float(row['Debit'].replace(',', '.')) if row['Debit'] else 0.0
            credit = float(row['Credit'].replace(',', '.')) if row['Credit'] else 0.0

            if debit > 0:
                montant = debit
                sens = 'D'
            else:
                montant = credit
                sens = 'C'

            # Conversion des dates
            ecriture_date = self._parse_date(row['EcritureDate'])
            piece_date = self._parse_date(row['PieceDate']) if row['PieceDate'] else None
            valid_date = self._parse_date(row['ValidDate']) if row['ValidDate'] else None
            date_let = self._parse_date(row['DateLet']) if row['DateLet'] else None

            # Création de l'objet EcritureBancaire
            ecriture = EcritureBancaire(
                journal_code=row['JournalCode'],
                journal_lib=row['JournalLib'],
                ecriture_num=row['EcritureNum'],
                ecriture_date=ecriture_date,
                compte_num=row['CompteNum'],
                compte_lib=row['CompteLib'],
                comp_aux_num=row['CompAuxNum'] if row['CompAuxNum'] else None,
                comp_aux_lib=row['CompAuxLib'] if row['CompAuxLib'] else None,
                piece_ref=row['PieceRef'] if row['PieceRef'] else None,
                piece_date=piece_date,
                ecriture_lib=row['EcritureLib'],
                debit=debit if debit > 0 else None,
                credit=credit if credit > 0 else None,
                ecriture_let=row['EcritureLet'] if row['EcritureLet'] else None,
                date_let=date_let,
                valid_date=valid_date,
                montant_devise=float(row['Montantdevise'].replace(',', '.')) if row['Montantdevise'] else None,
                id_devise=row['Idevise'] if row['Idevise'] else None,
                compte_final=compte_final,
                libelle_final=libelle_final,
                montant=montant,
                sens=sens,
                fec_file_id=fec_file_id
            )

            db.session.add(ecriture)

    def _parse_date(self, date_str):
        """Parse une date du FEC (format YYYYMMDD)"""
        if not date_str or len(date_str) != 8:
            return None

        try:
            return datetime.strptime(date_str, '%Y%m%d').date()
        except:
            return None