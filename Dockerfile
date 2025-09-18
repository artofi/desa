# Dockerfile
FROM python:3.11-slim

# Setting lingkungan
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# Buat direktori aplikasi
WORKDIR /app

# Salin file dependensi
COPY requirements.txt .

# Instal dependensi
RUN pip install --no-cache-dir -r requirements.txt

# Salin semua file proyek
COPY . .

# Buat folder yang diperlukan (untuk database, backup, dll)
RUN mkdir -p laporan/pdf backup static/charts template ekspor static/uploads/foto

# Expose port
EXPOSE $PORT
# Railway akan set PORT otomatis, jadi tidak perlu hardcode

# Jalankan aplikasi
CMD ["python", "wsgi.py"]
