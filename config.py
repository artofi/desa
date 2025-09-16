# config.py
import os

class Config:
    # Kunci rahasia aplikasi
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'rahasia-desaku-2025'
    
    # Database
    DATABASE = 'desa.db'
    
    # Folder utama
    UPLOAD_FOLDER = 'static/uploads/foto'
    PDF_FOLDER = 'laporan/pdf'
    BACKUP_FOLDER = 'backup'
    CHART_FOLDER = 'static/charts'
    TEMPLATE_FOLDER = 'template'
    EKSPOR_FOLDER = 'ekspor'

    @staticmethod
    def init_app(app):
        """
        Buat folder yang diperlukan saat aplikasi dijalankan
        Penting untuk deploy di Railway karena filesystem bersih setiap restart
        """
        folders = [
            'static/uploads/foto',
            'laporan/pdf',
            'backup',
            'static/charts',
            'template',
            'ekspor'
        ]
        
        for folder in folders:
            try:
                os.makedirs(folder, exist_ok=True)
                print(f"✅ Folder siap: {folder}")
            except Exception as e:
                print(f"❌ Gagal buat folder {folder}: {str(e)}")

# Konfigurasi tambahan jika butuh environment spesifik
class ProductionConfig(Config):
    DEBUG = False
    # Di Railway, bisa ambil dari env var
    SECRET_KEY = os.environ.get('SECRET_KEY')

class DevelopmentConfig(Config):
    DEBUG = True

# Pilih konfigurasi default
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': ProductionConfig
}
