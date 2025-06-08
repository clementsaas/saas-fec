from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app.models import db
from app.models.user import User
from app.models.organization import Organization

# Créer un Blueprint pour les routes d'authentification
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Page de connexion"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        # Vérifier que les champs sont remplis
        if not email or not password:
            flash('Veuillez remplir tous les champs', 'error')
            return render_template('login.html')

        # Chercher l'utilisateur par email
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            # Connexion réussie
            session['user_id'] = user.id
            session['user_nom'] = f"{user.prenom} {user.nom}"
            session['organization_id'] = user.organization_id

            flash(f'Bonjour {user.prenom} ! Connexion réussie.', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Email ou mot de passe incorrect', 'error')

    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Page d'inscription"""
    if request.method == 'POST':
        # Récupérer les données du formulaire
        prenom = request.form.get('prenom')
        nom = request.form.get('nom')
        email = request.form.get('email')
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        org_nom = request.form.get('org_nom')
        org_type = request.form.get('org_type')

        # Vérifications
        if not all([prenom, nom, email, password, password_confirm, org_nom, org_type]):
            flash('Veuillez remplir tous les champs', 'error')
            return render_template('register.html')

        if password != password_confirm:
            flash('Les mots de passe ne correspondent pas', 'error')
            return render_template('register.html')

        if len(password) < 6:
            flash('Le mot de passe doit contenir au moins 6 caractères', 'error')
            return render_template('register.html')

        # Vérifier si l'email existe déjà
        if User.query.filter_by(email=email).first():
            flash('Cet email est déjà utilisé', 'error')
            return render_template('register.html')

        try:
            # Créer l'organisation
            organization = Organization(
                nom=org_nom,
                type_org=org_type
            )
            db.session.add(organization)
            db.session.flush()  # Pour récupérer l'ID

            # Créer l'utilisateur
            user = User(
                prenom=prenom,
                nom=nom,
                email=email,
                organization_id=organization.id,
                is_admin_org=True  # Premier utilisateur = admin
            )
            user.set_password(password)
            db.session.add(user)

            db.session.commit()

            flash('Compte créé avec succès ! Vous pouvez maintenant vous connecter.', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            db.session.rollback()
            flash('Erreur lors de la création du compte. Veuillez réessayer.', 'error')
            print(f"Erreur: {e}")  # Pour le debug

    return render_template('register.html')


@auth_bp.route('/logout')
def logout():
    """Déconnexion"""
    session.clear()
    flash('Vous avez été déconnecté', 'info')
    return redirect(url_for('auth.login'))