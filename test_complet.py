from app import create_app
from app.models import db
from app.models.organization import Organization
from app.models.user import User
from app.models.societe import Societe
from app.models.fec_file import FecFile
from app.models.regle_affectation import RegleAffectation
from datetime import date

app = create_app()

with app.app_context():
    print("🔥 TEST COMPLET DU SAAS FEC 🔥")
    print("=" * 50)

    # 1. Créer une organisation
    org = Organization(nom="Cabinet Comptable Super", type_org="cabinet")
    db.session.add(org)
    db.session.commit()
    print(f"✅ Organisation créée : {org.nom} (ID: {org.id})")

    # 2. Créer un utilisateur
    user = User(
        email="comptable@cabinet.fr",
        nom="Dupont",
        prenom="Marie",
        organization_id=org.id,
        is_admin_org=True
    )
    user.set_password("motdepasse123")
    db.session.add(user)
    db.session.commit()
    print(f"✅ Utilisateur créé : {user.prenom} {user.nom} ({user.email})")

    # 3. Créer une société cliente
    societe = Societe(
        nom="Entreprise Client SARL",
        siret="12345678901234",
        date_debut_exercice=date(2024, 1, 1),
        date_fin_exercice=date(2024, 12, 31),
        organization_id=org.id
    )
    db.session.add(societe)
    db.session.commit()
    print(f"✅ Société créée : {societe.nom} (ID: {societe.id})")

    # 4. Créer un fichier FEC
    fec = FecFile(
        nom_fichier="fec_2024_test.txt",
        nom_original="FEC_EntrepriseClient_2024.txt",
        taille_fichier=150000,
        nb_lignes_total=5000,
        nb_lignes_bancaires=500,
        encodage_detecte="UTF-8",
        separateur_detecte="|",
        societe_id=societe.id
    )
    db.session.add(fec)
    db.session.commit()
    print(f"✅ Fichier FEC créé : {fec.nom_original} (ID: {fec.id})")

    # 5. Créer une règle d'affectation
    regle = RegleAffectation(
        nom="Virements bancaires",
        mots_cles=["VIREMENT", "VIR"],
        compte_destination="512100",
        libelle_destination="Banque - Compte principal",
        societe_id=societe.id
    )
    db.session.add(regle)
    db.session.commit()
    print(f"✅ Règle créée : {regle.nom} (ID: {regle.id})")

    print("=" * 50)
    print("🎉 SUCCÈS TOTAL ! TOUTES LES TABLES FONCTIONNENT !")
    print(f"📊 Organisations: {Organization.query.count()}")
    print(f"👥 Utilisateurs: {User.query.count()}")
    print(f"🏢 Sociétés: {Societe.query.count()}")
    print(f"📁 Fichiers FEC: {FecFile.query.count()}")
    print(f"⚙️ Règles: {RegleAffectation.query.count()}")