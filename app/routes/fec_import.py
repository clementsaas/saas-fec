from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
import os
from app.models import db
from app.models.societe import Societe
from app.models.fec_file import FecFile

# Blueprint pour les routes d'import FEC
fec_bp = Blueprint('fec', __name__)


@fec_bp.route('/import-fec')
def import_fec():
    """Page d'import de fichier FEC"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    return render_template('import_fec.html')


@fec_bp.route('/import-fec', methods=['POST'])
def upload_fec():
    """Traitement de l'upload du fichier FEC"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    try:
        # Récupérer les données du formulaire
        societe_nom = request.form.get('societe_nom')
        date_debut = request.form.get('date_debut') or None
        date_fin = request.form.get('date_fin') or None

        # Vérifier qu'un fichier a été uploadé
        if 'fec_file' not in request.files:
            flash('Aucun fichier sélectionné', 'error')
            return render_template('import_fec.html')

        file = request.files['fec_file']
        if file.filename == '':
            flash('Aucun fichier sélectionné', 'error')
            return render_template('import_fec.html')

        # Vérifier l'extension
        allowed_extensions = {'.txt', '.csv'}
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            flash('Format de fichier non autorisé. Utilisez .txt ou .csv', 'error')
            return render_template('import_fec.html')

        # Vérifications de base
        if not societe_nom:
            flash('Le nom de la société est obligatoire', 'error')
            return render_template('import_fec.html')

        # Créer ou récupérer la société
        organization_id = session['organization_id']
        societe = Societe.query.filter_by(
            nom=societe_nom,
            organization_id=organization_id
        ).first()

        if not societe:
            # Créer une nouvelle société
            from datetime import datetime
            societe = Societe(
                nom=societe_nom,
                organization_id=organization_id
            )
            if date_debut:
                societe.date_debut_exercice = datetime.strptime(date_debut, '%Y-%m-%d').date()
            if date_fin:
                societe.date_fin_exercice = datetime.strptime(date_fin, '%Y-%m-%d').date()

            db.session.add(societe)
            db.session.flush()  # Pour récupérer l'ID

        # Vérifier le nombre de FEC actifs (max 3)
        nb_fec_actifs = FecFile.query.filter_by(
            societe_id=societe.id,
            is_active=True
        ).count()

        if nb_fec_actifs >= 3:
            flash('Cette société a déjà 3 fichiers FEC actifs. Supprimez-en un avant d\'importer.', 'error')
            return render_template('import_fec.html')

        # Sauvegarder temporairement le fichier
        filename = secure_filename(file.filename)
        from flask import current_app
        upload_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(upload_path)

        # Traiter le fichier FEC
        from app.services.fec_processor import FecProcessor
        processor = FecProcessor()

        result = processor.process_fec_file(
            file_path=upload_path,
            original_filename=filename,
            societe_id=societe.id
        )

        # Supprimer le fichier temporaire
        os.remove(upload_path)

        if result['success']:
            db.session.commit()
            flash(
                f'✅ Import réussi ! {result["stats"]["nb_lignes_bancaires"]} écritures bancaires extraites sur {result["stats"]["nb_lignes_total"]} lignes.',
                'success')
            return redirect(url_for('fec.view_fec', fec_id=result['fec_file_id']))
        else:
            db.session.rollback()
            flash(f'❌ Erreur lors du traitement : {result["error"]}', 'error')
            return render_template('import_fec.html')

    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erreur inattendue : {str(e)}', 'error')
        print(f"Erreur upload FEC: {e}")  # Pour le debug
        return render_template('import_fec.html')


@fec_bp.route('/fec/<int:fec_id>')
def view_fec(fec_id):
    """Visualisation d'un fichier FEC importé"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    # Récupérer le fichier FEC
    fec_file = FecFile.query.get_or_404(fec_id)

    # Vérifier que l'utilisateur a accès à ce FEC (même organisation)
    from app.models.societe import Societe
    societe = Societe.query.get(fec_file.societe_id)
    if societe.organization_id != session['organization_id']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard'))

    # Récupérer les écritures bancaires
    from app.models.ecriture_bancaire import EcritureBancaire
    ecritures = EcritureBancaire.query.filter_by(
        fec_file_id=fec_id
    ).order_by(EcritureBancaire.ecriture_date.desc()).all()

    # Récupérer la liste des journaux (pour le filtre)
    journaux = db.session.query(
        EcritureBancaire.journal_code,
        EcritureBancaire.journal_lib
    ).filter_by(fec_file_id=fec_id).distinct().all()

    return render_template('view_fec.html',
                           fec_file=fec_file,
                           ecritures=ecritures,
                           journaux=journaux)