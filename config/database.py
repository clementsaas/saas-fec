import os


class Config:
    SECRET_KEY = 'dev-secret-key-a-changer'

    # Configuration PostgreSQL - MODIFIEZ LE MOT DE PASSE !
    DB_PASSWORD = 'aA0381801,'
    SQLALCHEMY_DATABASE_URI = f'postgresql://postgres:{DB_PASSWORD}@localhost:5432/saas_fec'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Dossier pour stocker les fichiers uploadés temporairement
    UPLOAD_FOLDER = 'static/uploads'

    # Taille maximum des fichiers uploadés (100 MB)
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024