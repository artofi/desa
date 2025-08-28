# config.py
import os

class Config:
    SECRET_KEY = 'rahasia-desaku-2025'
    DATABASE = 'desa.db'
    UPLOAD_FOLDER = 'static/uploads/foto'
    PDF_FOLDER = 'laporan/pdf'

    @staticmethod
    def init_app(app):
        os.makedirs('static/uploads/foto', exist_ok=True)
        os.makedirs('laporan/pdf', exist_ok=True)