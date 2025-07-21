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

    def process_fec_file(self, file_path, original_filename, societe_id, format_fec='standard'):
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

            # 4.5. Application du format spécifique (Pennylane si nécessaire)
            if format_fec == 'pennylane':
             df = self._apply_pennylane_formatting(df)

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
            print("🔄 Début sauvegarde des écritures bancaires...")
            try:
                self._save_ecritures_bancaires(ecritures_bancaires, fec_file.id)
                print("✅ Sauvegarde terminée avec succès")
            except Exception as save_error:
                print(f"❌ Erreur lors de la sauvegarde: {save_error}")
                raise save_error

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
            print(f"❌ Erreur traitement FEC: {e}")
            import traceback
            traceback.print_exc()  # Afficher la stack trace complète
            return {
                'success': False,
                'error': f'Erreur de traitement: {str(e)}'
            }

    def _detect_encoding(self, file_path):
        """Détecte l'encodage du fichier avec fallback robuste"""
        # 1. Essayer chardet d'abord
        with open(file_path, 'rb') as f:
            raw_data = f.read(50000)  # Plus de données pour meilleure détection

        result = chardet.detect(raw_data)
        detected_encoding = result['encoding']
        confidence = result['confidence']

        print(f"Chardet détecte: {detected_encoding} (confiance: {confidence})")

        # 2. Liste des encodages à tester par ordre de priorité pour les FEC français
        encodings_to_try = [
            'iso-8859-1',  # Très courant pour les FEC français
            'windows-1252',  # Variante Windows de ISO-8859-1
            'cp1252',  # Autre nom pour windows-1252
            'utf-8',  # Standard moderne
            'latin1'  # Équivalent à iso-8859-1
        ]

        # Ajouter l'encodage détecté en premier si confiance élevée
        if detected_encoding and confidence > 0.8:
            if detected_encoding not in encodings_to_try:
                encodings_to_try.insert(0, detected_encoding)

        # 3. Tester chaque encodage en essayant de lire le fichier
        for encoding in encodings_to_try:
            try:
                print(f"Test encodage: {encoding}")
                with open(file_path, 'r', encoding=encoding) as f:
                    # Essayer de lire les 5 premières lignes
                    for i in range(5):
                        line = f.readline()
                        if not line:  # Fin de fichier
                            break

                    print(f"✅ Encodage {encoding} fonctionne")
                    return encoding

            except UnicodeDecodeError as e:
                print(f"❌ Encodage {encoding} échoue: {e}")
                continue
            except Exception as e:
                print(f"❌ Erreur avec {encoding}: {e}")
                continue

        # 4. Dernier recours : forcer ISO-8859-1 (peut lire n'importe quoi)
        print("⚠️ Aucun encodage détecté, utilisation forcée d'ISO-8859-1")
        return 'iso-8859-1'

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
        """Extrait les écritures qui contiennent au moins une ligne bancaire (512*)"""
        # Utiliser les noms de colonnes par index pour éviter les problèmes d'encodage
        df.columns = self.required_columns[:len(df.columns)]

        # Identifier les numéros d'écriture qui contiennent au moins une ligne 512*
        ecritures_avec_512 = df[df['CompteNum'].str.startswith('512', na=False)]['EcritureNum'].unique()

        # Retourner TOUTES les lignes de ces écritures (512* ET contreparties)
        mask = df['EcritureNum'].isin(ecritures_avec_512)
        ecritures_completes = df[mask].copy()

        return ecritures_completes

    def _save_ecritures_bancaires(self, ecritures_df, fec_file_id):
        """Sauvegarde les écritures bancaires en base avec logique de contrepartie"""

        # Grouper toutes les écritures par EcritureNum pour analyser les contreparties
        ecritures_completes = ecritures_df.groupby('EcritureNum')

        # Traiter chaque groupe d'écritures
        for ecriture_num, groupe_ecritures in ecritures_completes:
            # Identifier les lignes bancaires (512*) et non-bancaires
            lignes_bancaires = []
            lignes_contreparties = []

            for _, ligne in groupe_ecritures.iterrows():
                compte_final = ligne['CompAuxNum'] if ligne['CompAuxNum'] else ligne['CompteNum']
                libelle_final = ligne['CompAuxLib'] if ligne['CompAuxLib'] else ligne['CompteLib']

                if compte_final.startswith('512'):
                    lignes_bancaires.append({
                        'ligne': ligne,
                        'compte_final': compte_final,
                        'libelle_final': libelle_final
                    })
                else:
                    # Calculer le montant de la contrepartie
                    debit = float(ligne['Debit'].replace(',', '.')) if ligne['Debit'] else 0.0
                    credit = float(ligne['Credit'].replace(',', '.')) if ligne['Credit'] else 0.0
                    montant_contrepartie = max(debit, credit)

                    lignes_contreparties.append({
                        'ligne': ligne,
                        'compte_final': compte_final,
                        'libelle_final': libelle_final,
                        'montant': montant_contrepartie
                    })

            # Déterminer la contrepartie principale (celle avec le montant le plus élevé)
            if lignes_contreparties:
                contrepartie_principale = max(lignes_contreparties, key=lambda x: x['montant'])
                compte_contrepartie = contrepartie_principale['compte_final']
                libelle_contrepartie = contrepartie_principale['libelle_final']
            else:
                # Cas où il n'y a pas de contrepartie identifiable
                compte_contrepartie = "AUTRE"
                libelle_contrepartie = "Compte non identifié"

            # Sauvegarder UNIQUEMENT les lignes bancaires avec leur contrepartie
            for ligne_bancaire in lignes_bancaires:
                row = ligne_bancaire['ligne']

                # Calcul du montant et sens pour la ligne bancaire
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

                # Création de l'objet EcritureBancaire avec la contrepartie correcte
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
                    compte_final=ligne_bancaire['compte_final'],
                    libelle_final=ligne_bancaire['libelle_final'],
                    montant=montant,
                    sens=sens,
                    fec_file_id=fec_file_id,
                    # AJOUT : Champs de contrepartie
                    compte_contrepartie=compte_contrepartie,
                    libelle_contrepartie=libelle_contrepartie
                )

                db.session.add(ecriture)

                # Commit par batch de 100 pour optimiser
                if len(lignes_bancaires) % 100 == 0:
                    db.session.flush()

        # Commit final des dernières écritures
        db.session.flush()

    def _parse_date(self, date_str):
        """Parse une date du FEC (format YYYYMMDD)"""
        if not date_str or len(date_str) != 8:
            return None

        try:
            return datetime.strptime(date_str, '%Y%m%d').date()
        except:
            return None
        
    def _apply_pennylane_formatting(self, df):
    print("🔧 Application du format Pennylane...")
    
    # Suffixes à détecter et supprimer
    pennylane_suffixes = [
        '(Import/Export)',
        '(Pas de TVA)',
        '(TVA 20%)',
        '(TVA 5.5%)',
        '(TVA 10%)',
        '(TVA 2.1%)',
        '(Intracom)'
    ]
    
    modifications_count = 0
    
    for index, row in df.iterrows():
        compte_num = str(row['CompteNum']) if pd.notna(row['CompteNum']) else ''
        compte_lib = str(row['CompteLib']) if pd.notna(row['CompteLib']) else ''
        
        # Vérifier si le libellé contient un des suffixes (insensible à la casse)
        suffix_found = False
        for suffix in pennylane_suffixes:
            if suffix.lower() in compte_lib.lower():
                suffix_found = True
                break
        
        if suffix_found and len(compte_num) > 0:
            # Modifier le dernier caractère de CompteNum par "0"
            new_compte_num = compte_num[:-1] + '0'
            df.at[index, 'CompteNum'] = new_compte_num
            modifications_count += 1
            
        # Nettoyer le libellé en supprimant tous les suffixes
        new_compte_lib = compte_lib
        for suffix in pennylane_suffixes:
            # Suppression insensible à la casse
            import re
            pattern = re.escape(suffix)
            new_compte_lib = re.sub(pattern, '', new_compte_lib, flags=re.IGNORECASE)
        
        # Nettoyer les espaces en trop
        new_compte_lib = new_compte_lib.strip()
        df.at[index, 'CompteLib'] = new_compte_lib
    
    print(f"✅ Format Pennylane appliqué : {modifications_count} comptes modifiés")
    return df