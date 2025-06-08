from app import create_app
from app.models import db
from app.models.organization import Organization

# Créer l'application
app = create_app()

# Tester l'insertion
with app.app_context():
    # Créer une nouvelle organisation
    org = Organization(
        nom="Cabinet Test",
        type_org="cabinet"
    )

    # L'ajouter à la base
    db.session.add(org)
    db.session.commit()

    print("✅ Organisation créée avec succès !")
    print(f"ID: {org.id}, Nom: {org.nom}, Type: {org.type_org}")

    # Lire toutes les organisations
    all_orgs = Organization.query.all()
    print(f"📊 Nombre total d'organisations: {len(all_orgs)}")