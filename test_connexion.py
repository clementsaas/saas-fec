from config.database import Config

print("🔍 Test de configuration...")
print(f"URL de connexion : {Config.SQLALCHEMY_DATABASE_URI}")
print("✅ Configuration chargée avec succès !")