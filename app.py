# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, get_flashed_messages, send_file, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
import os
from datetime import datetime
from fpdf import FPDF
import pandas as pd
import re
import shutil
import threading
import time
from config import Config
#import mstplotlib
import matplotlib
matplotlib.use('Agg')  # Penting: agar jalan di web server
import matplotlib.pyplot as plt
import os
from flask import send_file


# Buat folder
os.makedirs("laporan/pdf", exist_ok=True)
os.makedirs("static/uploads/foto", exist_ok=True)
os.makedirs("template", exist_ok=True)
os.makedirs("ekspor", exist_ok=True)
os.makedirs("backup", exist_ok=True)

# Inisialisasi Flask
app = Flask(__name__)
app.config.from_object(Config)
Config.init_app(app)

def init_log_table():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS log_penghapusan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nik TEXT NOT NULL,
            nama TEXT NOT NULL,
            alasan_hapus TEXT,
            dusun TEXT,
            tanggal_hapus DATETIME DEFAULT CURRENT_TIMESTAMP,
            dihapus_oleh TEXT
        )
    """)
    conn.commit()
    conn.close()

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Helper: Koneksi database
def get_db():
    conn = sqlite3.connect('desa.db')
    conn.row_factory = sqlite3.Row
    return conn

# Fungsi sanitasi nama file
def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', filename)

# Class User untuk Flask-Login
class User(UserMixin):
    def __init__(self, id, username, role, dusun=None, nik_masyarakat=None):
        self.id = id
        self.username = username
        self.role = role
        self.dusun = dusun
        self.nik_masyarakat = nik_masyarakat

# Dictionary untuk menyimpan user
users = {}

# Load user dari database
@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)

def init_db():
    conn = sqlite3.connect('desa.db')
    # Tabel penduduk
    conn.execute('''
        CREATE TABLE IF NOT EXISTS penduduk (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nomor_kk TEXT,
            nik TEXT UNIQUE,
            nama TEXT,
            hubungan TEXT,
            jenis_kelamin TEXT,
            tempat_lahir TEXT,
            tanggal_lahir TEXT,
            agama TEXT,
            status_perkawinan TEXT,
            pendidikan TEXT,
            pekerjaan TEXT,
            alamat TEXT,
            rt_rw TEXT,
            dusun TEXT,
            golongan_darah TEXT,
            kesejahteraan TEXT,
            tanggal_input TEXT,
            foto_ktp TEXT
        )
    ''')
    # Tabel user
    conn.execute('''
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT,
            dusun TEXT,
            nik_masyarakat TEXT
        )
    ''')
    conn.close()

def load_users_from_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, password, role, dusun, nik_masyarakat FROM user")
    rows = cursor.fetchall()
    conn.close()
    
    users.clear()
    for row in rows:
        users[row['username']] = User(
            id=row['username'],
            username=row['username'],
            role=row['role'],
            dusun=row['dusun'],
            nik_masyarakat=row['nik_masyarakat']
        )

# --- Inisialisasi Database & User Awal ---
if not os.path.exists('desa.db'):
    init_db()
    # Tambah user default
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO user (username, password, role) VALUES (?, ?, ?)",
                 ('admin', '1234', 'admin'))
    conn.execute("INSERT OR IGNORE INTO user (username, password, role, dusun) VALUES (?, ?, ?, ?)",
                 ('kepala_satu', '1234', 'kepala_dusun', 'SATU'))
    conn.execute("INSERT OR IGNORE INTO user (username, password, role, nik_masyarakat) VALUES (?, ?, ?, ?)",
                 ('warga1', '1234', 'masyarakat', '1234567890123456'))
    conn.commit()
    conn.close()

load_users_from_db()  # Muat user dari db

# --- BACKUP OTOMATIS ---
def backup_db():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join("backup", f"desa_{timestamp}.db")
    try:
        shutil.copy("desa.db", backup_path)
        print(f"✅ Backup berhasil: {backup_path}")
    except Exception as e:
        print(f"❌ Gagal backup: {str(e)}")

def start_backup_scheduler():
    def run():
        while True:
            backup_db()
            time.sleep(86400)  # 24 jam
    thread = threading.Thread(target=run, daemon=True)
    thread.start()

@app.route('/')
@login_required
def index():
    # Ambil parameter
    search_query = request.args.get('q', '').strip()
    view_mode = request.args.get('view', 'kk')

    # Variabel default
    total_jiwa = total_kk = total_dusun = 0
    rows = []

    # ============ 1. Ambil Statistik ============
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Base query
            base_jiwa = "SELECT COUNT(*) FROM penduduk"
            base_kk = "SELECT COUNT(DISTINCT nomor_kk) FROM penduduk WHERE nomor_kk IS NOT NULL AND TRIM(nomor_kk) != ''"
            base_dusun = "SELECT COUNT(DISTINCT dusun) FROM penduduk WHERE dusun IS NOT NULL AND TRIM(dusun) != ''"
            params = ()

            # Filter role
            if current_user.role == 'kepala_dusun':
                base_jiwa += " WHERE dusun = ?"
                base_kk += " AND dusun = ?"
                base_dusun += " AND dusun = ?"
                params = (current_user.dusun,)
            elif current_user.role == 'masyarakat':
                base_jiwa += " WHERE nik = ?"
                base_kk += " AND nik = ?"
                base_dusun += " AND nik = ?"
                params = (current_user.nik_masyarakat,)

            # Eksekusi
            cursor.execute(base_jiwa, params)
            total_jiwa = cursor.fetchone()[0]

            cursor.execute(base_kk, params)
            total_kk = cursor.fetchone()[0]

            cursor.execute(base_dusun, params)
            total_dusun = cursor.fetchone()[0]

    except Exception as e:
        print(f"Statistik gagal: {str(e)[:100]}...")

    # ============ 2. Ambil Data Utama ============
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            base_query = """
                SELECT nomor_kk, nik, nama, hubungan, alamat, dusun, jenis_kelamin, 
                       pendidikan, kesejahteraan, tanggal_input
                FROM penduduk
            """
            params = ()

            # Filter role
            if current_user.role == 'kepala_dusun':
                base_query += " WHERE dusun = ?"
                params = (current_user.dusun,)
            elif current_user.role == 'masyarakat':
                base_query += " WHERE nik = ?"
                params = (current_user.nik_masyarakat,)

            # Pencarian
            if search_query:
                search_param = f'%{search_query}%'
                if "WHERE" in base_query:
                    # Sudah ada WHERE → pakai AND
                    base_query += " AND (nomor_kk LIKE ? OR nik LIKE ? OR nama LIKE ?)"
                else:
                    # Belum ada WHERE → pakai WHERE
                    base_query += " WHERE (nomor_kk LIKE ? OR nik LIKE ? OR nama LIKE ?)"
                params += (search_param, search_param, search_param)

            # Urutkan
            if view_mode == 'nik':
                order_by = " ORDER BY nama"
            else:
                order_by = " ORDER BY nomor_kk, CASE WHEN hubungan='Kepala Keluarga' THEN 0 ELSE 1 END, nama"

            cursor.execute(base_query + order_by, params)
            rows = cursor.fetchall()

    except Exception as e:
        print(f"Data utama gagal: {str(e)[:100]}...")
        rows = []

    # ============ 3. Kirim ke Template ============
    if view_mode == 'nik':
        return render_template('index_nik.html',
                             penduduk=rows,
                             q=search_query,
                             total_jiwa=total_jiwa,
                             total_kk=total_kk,
                             total_dusun=total_dusun)
    else:
        keluarga = {}
        for row in rows:
            kk = row['nomor_kk']
            if kk not in keluarga:
                keluarga[kk] = {
                    'kepala': '—',
                    'alamat': row['alamat'],
                    'dusun': row['dusun'],
                    'anggota': []
                }
            if row['hubungan'] == 'Kepala Keluarga':
                keluarga[kk]['kepala'] = row['nama']
            keluarga[kk]['anggota'].append(row)
        return render_template('index.html',
                             keluarga=keluarga,
                             q=search_query,
                             total_jiwa=total_jiwa,
                             total_kk=total_kk,
                             total_dusun=total_dusun)
# --- LOGIN & LOGOUT ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT username, password, role, dusun, nik_masyarakat FROM user WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row['password'] == password:
            user_obj = User(
                id=row['username'],
                username=row['username'],
                role=row['role'],
                dusun=row['dusun'],
                nik_masyarakat=row['nik_masyarakat']
            )
            login_user(user_obj)
            return redirect(url_for('index'))
        flash("Login gagal! Username atau password salah.", "danger")
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- TAMBAH DATA ---
@app.route('/tambah', methods=['GET', 'POST'])
@login_required
def tambah():
    programs = ["BPJS KIS", "BPJS Mandiri", "PKH", "Sembako", "PIP", "BLT", "Tidak Ada"]
    if request.method == 'POST':
        nama = request.form['nama'].strip().upper()
        nik = request.form['nik'].strip()
        nomor_kk = request.form['nomor_kk'].strip()
        dusun = request.form.get('dusun', '').strip()

        errors = validasi_data(nama, nik, nomor_kk, dusun)
        if errors:
            for e in errors:
                flash(e, "danger")
            return redirect(url_for('tambah'))
        data = {
            'nomor_kk': request.form['nomor_kk'],
            'nik': request.form['nik'],
            'nama': request.form['nama'],
            'hubungan': request.form['hubungan'],
            'jenis_kelamin': request.form['jenis_kelamin'],
            'tempat_lahir': request.form['tempat_lahir'],
            'tanggal_lahir': request.form['tanggal_lahir'],
            'agama': request.form['agama'],
            'status_perkawinan': request.form['status_perkawinan'],
            'pendidikan': request.form['pendidikan'],
            'pekerjaan': request.form['pekerjaan'],
            'alamat': request.form['alamat'],
            'rt_rw': request.form['rt_rw'],
            'dusun': request.form.get('dusun', ''),
            'golongan_darah': request.form['golongan_darah'],
            'kesejahteraan': ','.join(request.form.getlist('kesejahteraan')),
            'tanggal_input': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'foto_ktp': ''
        }
        conn = get_db()
        try:
            conn.execute('''
                INSERT INTO penduduk (nomor_kk, nik, nama, hubungan, jenis_kelamin, tempat_lahir, tanggal_lahir, agama, status_perkawinan, pendidikan, pekerjaan, alamat, rt_rw, dusun, golongan_darah, kesejahteraan, tanggal_input, foto_ktp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', tuple(data.values()))
            conn.commit()
            flash("Data berhasil ditambahkan!", "success")
        except sqlite3.IntegrityError:
            flash("NIK sudah ada! Data tidak bisa ditambahkan.", "danger")
        finally:
            conn.close()
        return redirect(url_for('index'))
    
    programs = ["BPJS KIS", "BPJS Mandiri", "PKH", "Sembako", "PIP", "BLT", "Tidak Ada"]
    return render_template('tambah.html', programs=programs)

# --- EDIT DATA ---
@app.route('/edit/<nik_old>', methods=['GET', 'POST'])
@login_required
def edit(nik_old):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM penduduk WHERE nik = ?", (nik_old,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        flash("Data tidak ditemukan.", "danger")
        return redirect(url_for('index'))

    # Cek hak akses berdasarkan role
    if current_user.role == 'kepala_dusun' and row['dusun'] != current_user.dusun:
        flash("Anda tidak diizinkan mengedit data di dusun ini.", "danger")
        return redirect(url_for('index'))
    elif current_user.role == 'masyarakat' and row['nik'] != current_user.nik_masyarakat:
        flash("Anda hanya bisa mengedit data milik Anda.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Ambil data dari form
        nama = request.form['nama'].strip().upper()
        nik = request.form['nik'].strip()
        nomor_kk = request.form['nomor_kk'].strip()
        dusun = request.form.get('dusun', '').strip()

        # Validasi data
        errors = validasi_data(nama, nik, nomor_kk, dusun)
        if errors:
            for e in errors:
                flash(e, "danger")
            # Kembalikan data yang diisi agar tidak hilang
            return render_template('edit.html', 
                                 data=request.form, 
                                 programs=["BPJS KIS", "BPJS Mandiri", "PKH", "Sembako", "PIP", "BLT", "Tidak Ada"],
                                 current_kesejahteraan=request.form.getlist('kesejahteraan'))

        # Siapkan data untuk update
        data = {
            'nomor_kk': nomor_kk,
            'nik': nik,
            'nama': nama,
            'hubungan': request.form['hubungan'],
            'jenis_kelamin': request.form['jenis_kelamin'],
            'tempat_lahir': request.form['tempat_lahir'],
            'tanggal_lahir': request.form['tanggal_lahir'],
            'agama': request.form['agama'],
            'status_perkawinan': request.form['status_perkawinan'],
            'pendidikan': request.form['pendidikan'],
            'pekerjaan': request.form['pekerjaan'],
            'alamat': request.form['alamat'],
            'rt_rw': request.form['rt_rw'],
            'dusun': dusun,
            'golongan_darah': request.form['golongan_darah'],
            'kesejahteraan': ','.join(request.form.getlist('kesejahteraan')),
            'tanggal_input': row['tanggal_input'],  # Pertahankan
            'foto_ktp': row['foto_ktp']  # Pertahankan
        }

        # Update ke database
        conn = get_db()
        try:
            conn.execute('''
                UPDATE penduduk SET nomor_kk=?, nik=?, nama=?, hubungan=?, jenis_kelamin=?, tempat_lahir=?, tanggal_lahir=?, agama=?, status_perkawinan=?, pendidikan=?, pekerjaan=?, alamat=?, rt_rw=?, dusun=?, golongan_darah=?, kesejahteraan=?, tanggal_input=?, foto_ktp=?
                WHERE nik=?
            ''', tuple(data.values()) + (nik_old,))
            conn.commit()
            flash("Data berhasil diubah!", "success")
        except sqlite3.IntegrityError:
            flash("NIK sudah digunakan oleh orang lain!", "danger")
        except Exception as e:
            flash(f"Terjadi kesalahan saat menyimpan: {str(e)}", "danger")
        finally:
            conn.close()

        return redirect(url_for('index'))

    # Jika GET, tampilkan form
    programs = ["BPJS KIS", "BPJS Mandiri", "PKH", "Sembako", "PIP", "BLT", "Tidak Ada"]
    current_kesejahteraan = row['kesejahteraan'].split(",") if row['kesejahteraan'] else []
    return render_template('edit.html', 
                         data=row, 
                         programs=programs, 
                         current_kesejahteraan=current_kesejahteraan)


# --- UPLOAD EXCEL ---
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if current_user.role not in ['admin', 'kepala_dusun']:
        flash("Anda tidak diizinkan mengakses halaman ini.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        if 'file' not in request.files:
            return render_template('upload.html', result={'success': False, 'message': 'File tidak ditemukan.'})
        file = request.files['file']
        if file.filename == '':
            return render_template('upload.html', result={'success': False, 'message': 'Belum pilih file.'})
        if not file.filename.endswith('.xlsx'):
            return render_template('upload.html', result={'success': False, 'message': 'Format harus .xlsx'})
        try:
            df = pd.read_excel(file)
            required_cols = {'nik', 'nomor_kk', 'nama', 'hubungan', 'jenis_kelamin', 'dusun'}
            if not required_cols.issubset(df.columns.str.strip()):
                return render_template('upload.html', result={'success': False, 'message': f'Kolom tidak lengkap: {", ".join(required_cols)}'})
            df = df.fillna('')
            df['nik'] = df['nik'].astype(str).str.strip()
            df['nomor_kk'] = df['nomor_kk'].astype(str).str.strip()
            new_count = 0
            update_count = 0
            failed_count = 0
            conn = get_db()
            for _, row in df.iterrows():
                try:
                    conn.execute('''
                        INSERT OR REPLACE INTO penduduk 
                        (nik, nomor_kk, nama, hubungan, jenis_kelamin, tempat_lahir, tanggal_lahir,
                         agama, status_perkawinan, pendidikan, pekerjaan, alamat, rt_rw, dusun,
                         golongan_darah, kesejahteraan, tanggal_input, foto_ktp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        row['nik'], row['nomor_kk'], row['nama'], row['hubungan'], row['jenis_kelamin'],
                        row.get('tempat_lahir', ''), row.get('tanggal_lahir', ''),
                        row.get('agama', ''), row.get('status_perkawinan', ''), row.get('pendidikan', ''),
                        row.get('pekerjaan', ''), row.get('alamat', ''), row.get('rt_rw', ''), row['dusun'],
                        row.get('golongan_darah', ''), row.get('kesejahteraan', ''),
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row.get('foto_ktp', '')
                    ))
                    conn.commit()
                    update_count += 1
                except sqlite3.IntegrityError:
                    failed_count += 1
            conn.close()
            return render_template('upload.html', result={'success': True, 'message': 'Data berhasil diimpor!', 'new_count': new_count, 'update_count': update_count, 'failed_count': failed_count})
        except Exception as e:
            return render_template('upload.html', result={'success': False, 'message': f'Error membaca file: {str(e)}'})
    return render_template('upload.html')

# --- CETAK KK ---
@app.route('/cetak/kk/<nomor_kk>')
@login_required
def cetak_kk(nomor_kk):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM penduduk WHERE nomor_kk = ? ORDER BY CASE WHEN hubungan='Kepala Keluarga' THEN 0 ELSE 1 END, nama", (nomor_kk,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        flash("Data tidak ditemukan untuk nomor KK ini.", "warning")
        return redirect(url_for('index'))

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("helvetica", 'B', 16)
    pdf.cell(0, 10, "KARTU KELUARGA", ln=True, align='C')
    pdf.set_font("helvetica", '', 12)
    pdf.cell(0, 8, f"No. KK: {nomor_kk}", ln=True, align='C')
    pdf.ln(10)

    pdf.set_font("helvetica", 'B', 8)
    col_widths = [28, 35, 18, 25, 25, 18, 20, 20, 25, 20, 20]
    headers = ["NIK", "Nama", "JK", "Tmpt Lahir", "Tgl Lahir", "Agama", "Status", "Pendidikan", "Pekerjaan", "Gol. Darah", "Hubungan"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, 1, 0, 'C')
    pdf.ln(8)

    pdf.set_font("helvetica", '', 7)
    for row in rows:
        pdf.cell(col_widths[0], 8, str(row['nik']), 1)
        pdf.cell(col_widths[1], 8, row['nama'], 1)
        pdf.cell(col_widths[2], 8, row['jenis_kelamin'], 1)
        pdf.cell(col_widths[3], 8, row['tempat_lahir'], 1)
        pdf.cell(col_widths[4], 8, row['tanggal_lahir'], 1)
        pdf.cell(col_widths[5], 8, row['agama'], 1)
        pdf.cell(col_widths[6], 8, row['status_perkawinan'], 1)
        pdf.cell(col_widths[7], 8, row['pendidikan'], 1)
        pdf.cell(col_widths[8], 8, row['pekerjaan'], 1)
        pdf.cell(col_widths[9], 8, row['golongan_darah'], 1)
        pdf.cell(col_widths[10], 8, row['hubungan'], 1)
        pdf.ln(8)

    os.makedirs("laporan/pdf", exist_ok=True)
    safe_kk = sanitize_filename(nomor_kk)
    filename = os.path.join("laporan", "pdf", f"kk_{safe_kk}.pdf")
    pdf.output(filename)
    return send_file(filename, as_attachment=True)

# --- CETAK SEMUA KK ---
@app.route('/cetak/semua/kk')
@login_required
def cetak_semua_kk():
    conn = get_db()
    kk_rows = conn.execute("""
        SELECT DISTINCT nomor_kk FROM penduduk 
        WHERE nomor_kk IS NOT NULL AND TRIM(nomor_kk) != ''
        ORDER BY nomor_kk
    """).fetchall()
    conn.close()

    kks = [row['nomor_kk'] for row in kk_rows]
    if not kks:
        flash("Tidak ada data KK untuk dicetak.", "info")
        return redirect(url_for('index'))

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)

    for nomor_kk in kks:
        conn = get_db()
        rows = conn.execute("SELECT * FROM penduduk WHERE nomor_kk = ? ORDER BY CASE WHEN hubungan='Kepala Keluarga' THEN 0 ELSE 1 END, nama", (nomor_kk,)).fetchall()
        conn.close()

        if not rows:
            continue

        pdf.add_page()
        pdf.set_font("helvetica", 'B', 16)
        pdf.cell(0, 10, "KARTU KELUARGA", ln=True, align='C')
        pdf.set_font("helvetica", '', 12)
        pdf.cell(0, 8, f"No. KK: {nomor_kk}", ln=True, align='C')
        pdf.ln(10)

        # Tabel (sama seperti di atas)
        pdf.set_font("helvetica", 'B', 8)
        col_widths = [28, 35, 18, 25, 25, 18, 20, 20, 25, 20, 20]
        headers = ["NIK", "Nama", "JK", "Tmpt Lahir", "Tgl Lahir", "Agama", "Status", "Pendidikan", "Pekerjaan", "Gol. Darah", "Hubungan"]
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 8, h, 1, 0, 'C')
        pdf.ln(8)

        pdf.set_font("helvetica", '', 7)
        for row in rows:
            pdf.cell(col_widths[0], 8, str(row['nik']), 1)
            pdf.cell(col_widths[1], 8, row['nama'], 1)
            pdf.cell(col_widths[2], 8, row['jenis_kelamin'], 1)
            pdf.cell(col_widths[3], 8, row['tempat_lahir'], 1)
            pdf.cell(col_widths[4], 8, row['tanggal_lahir'], 1)
            pdf.cell(col_widths[5], 8, row['agama'], 1)
            pdf.cell(col_widths[6], 8, row['status_perkawinan'], 1)
            pdf.cell(col_widths[7], 8, row['pendidikan'], 1)
            pdf.cell(col_widths[8], 8, row['pekerjaan'], 1)
            pdf.cell(col_widths[9], 8, row['golongan_darah'], 1)
            pdf.cell(col_widths[10], 8, row['hubungan'], 1)
            pdf.ln(8)

    os.makedirs("laporan/pdf", exist_ok=True)
    filepath = "laporan/pdf/semua_kk.pdf"
    pdf.output(filepath)
    return send_file(filepath, as_attachment=True)

# --- CETAK DARI NIK ---
@app.route('/cetak/kk/dari-nik', methods=['GET', 'POST'])
@login_required
def cetak_kk_dari_nik():
    if request.method == 'POST':
        nik = request.form['nik'].strip()
        if not nik:
            flash("NIK tidak boleh kosong.", "danger")
            return redirect(url_for('cetak_kk_dari_nik'))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT nomor_kk FROM penduduk WHERE nik = ?", (nik,))
        result = cursor.fetchone()
        conn.close()

        if not result:
            flash("NIK tidak ditemukan.", "danger")
            return redirect(url_for('cetak_kk_dari_nik'))

        nomor_kk = result['nomor_kk']
        if not nomor_kk or not nomor_kk.strip():
            flash("NIK ini tidak memiliki nomor KK.", "warning")
            return redirect(url_for('cetak_kk_dari_nik'))

        return redirect(url_for('cetak_kk', nomor_kk=nomor_kk))

    return render_template('cetak_kk_dari_nik.html')

# --- CETAK LAPORAN (PILIHAN) ---
@app.route('/cetak')
@login_required
def cetak_pilihan():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT dusun FROM penduduk WHERE dusun IS NOT NULL AND TRIM(dusun) != '' ORDER BY dusun")
    dusun_list = [row['dusun'] for row in cursor.fetchall()]
    conn.close()
    return render_template('cetak_pilihan.html', dusun_list=dusun_list)

# --- CETAK NIK SEMUA ---
@app.route('/cetak/daftar/semua')
@login_required
def cetak_daftar_semua():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT nomor_kk, nik, nama, hubungan, dusun, jenis_kelamin, 
               pendidikan, pekerjaan, alamat, kesejahteraan 
        FROM penduduk 
        ORDER BY dusun, nomor_kk, 
                 CASE WHEN hubungan = 'Kepala Keluarga' THEN 0 ELSE 1 END, 
                 nama
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        flash("Tidak ada data untuk dicetak.", "info")
        return redirect(url_for('index'))

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("helvetica", 'B', 16)
    pdf.cell(0, 10, "DAFTAR SEMUA PENDUDUK", ln=True, align='C')
    pdf.set_font("helvetica", '', 12)
    pdf.cell(0, 8, "Desa Nagori Bahapal Raya", ln=True, align='C')
    pdf.ln(10)

    pdf.set_font("helvetica", 'B', 8)
    col_widths = [25, 28, 35, 25, 18, 20, 20, 25, 25, 30]
    headers = ["No. KK", "NIK", "Nama", "Hubungan", "JK", "Pendidikan", "Pekerjaan", "Dusun", "Alamat", "Kesejahteraan"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, 1, 0, 'C')
    pdf.ln(8)

    pdf.set_font("helvetica", '', 7)
    for row in rows:
        pdf.cell(col_widths[0], 8, row['nomor_kk'] or '-', 1)
        pdf.cell(col_widths[1], 8, str(row['nik']), 1)
        pdf.cell(col_widths[2], 8, row['nama'], 1)
        pdf.cell(col_widths[3], 8, row['hubungan'], 1)
        pdf.cell(col_widths[4], 8, row['jenis_kelamin'], 1)
        pdf.cell(col_widths[5], 8, row['pendidikan'], 1)
        pdf.cell(col_widths[6], 8, row['pekerjaan'], 1)
        pdf.cell(col_widths[7], 8, row['dusun'], 1)
        pdf.cell(col_widths[8], 8, row['alamat'], 1)
        kesejahteraan = row['kesejahteraan'].replace(',', ', ') if row['kesejahteraan'] else '-'
        pdf.cell(col_widths[9], 8, kesejahteraan, 1)
        pdf.ln(8)

    os.makedirs("laporan/pdf", exist_ok=True)
    filename = "laporan/pdf/daftar_semua_penduduk.pdf"
    pdf.output(filename)
    return send_file(filename, as_attachment=True)

# --- CETAK NIK PER DUSUN ---
@app.route('/cetak/daftar/dusun')
@login_required
def cetak_daftar_dusun():
    dusun = request.args.get('dusun', '').strip()
    if not dusun:
        flash("Dusun tidak valid.", "danger")
        return redirect(url_for('cetak_pilihan'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT nomor_kk, nik, nama, hubungan, jenis_kelamin, 
               pendidikan, pekerjaan, alamat, kesejahteraan 
        FROM penduduk 
        WHERE dusun = ? 
        ORDER BY nomor_kk, 
                 CASE WHEN hubungan = 'Kepala Keluarga' THEN 0 ELSE 1 END, 
                 nama
    """, (dusun,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        flash(f"Tidak ada data di Dusun {dusun}.", "info")
        return redirect(url_for('cetak_pilihan'))

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("helvetica", 'B', 16)
    pdf.cell(0, 10, f"DAFTAR PENDUDUK DUSUN {dusun.upper()}", ln=True, align='C')
    pdf.ln(10)

    pdf.set_font("helvetica", 'B', 8)
    col_widths = [25, 28, 35, 25, 18, 20, 20, 25, 30]
    headers = ["No. KK", "NIK", "Nama", "Hubungan", "JK", "Pendidikan", "Pekerjaan", "Alamat", "Kesejahteraan"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, 1, 0, 'C')
    pdf.ln(8)

    pdf.set_font("helvetica", '', 7)
    for row in rows:
        pdf.cell(col_widths[0], 8, row['nomor_kk'] or '-', 1)
        pdf.cell(col_widths[1], 8, str(row['nik']), 1)
        pdf.cell(col_widths[2], 8, row['nama'], 1)
        pdf.cell(col_widths[3], 8, row['hubungan'], 1)
        pdf.cell(col_widths[4], 8, row['jenis_kelamin'], 1)
        pdf.cell(col_widths[5], 8, row['pendidikan'], 1)
        pdf.cell(col_widths[6], 8, row['pekerjaan'], 1)
        pdf.cell(col_widths[7], 8, row['alamat'], 1)
        kesejahteraan = row['kesejahteraan'].replace(',', ', ') if row['kesejahteraan'] else '-'
        pdf.cell(col_widths[8], 8, kesejahteraan, 1)
        pdf.ln(8)

    os.makedirs("laporan/pdf", exist_ok=True)
    safe_dusun = sanitize_filename(dusun)
    filename = f"laporan/pdf/daftar_dusun_{safe_dusun}.pdf"
    pdf.output(filename)
    return send_file(filename, as_attachment=True)

@app.route('/statistik')
@login_required
def statistik():
    conn = get_db()
    cursor = conn.cursor()

    # Base query dan parameter
    base_where = ""
    params = ()

    # Filter berdasarkan role
    if current_user.role == 'kepala_dusun':
        base_where = "dusun = ?"
        params = (current_user.dusun,)
    elif current_user.role == 'masyarakat':
        base_where = "nik = ?"
        params = (current_user.nik_masyarakat,)

    # 1. Total Jiwa
    jiwa_query = "SELECT COUNT(*) FROM penduduk"
    if base_where:
        jiwa_query += " WHERE " + base_where
    cursor.execute(jiwa_query, params)
    total_jiwa = cursor.fetchone()[0]

    # 2. Total KK
    kk_query = "SELECT COUNT(DISTINCT nomor_kk) FROM penduduk"
    kk_conditions = []
    kk_params = list(params)

    if base_where:
        kk_conditions.append(base_where)
    kk_conditions.append("nomor_kk IS NOT NULL")
    kk_conditions.append("TRIM(nomor_kk) != ''")

    if kk_conditions:
        kk_query += " WHERE " + " AND ".join(kk_conditions)

    cursor.execute(kk_query, kk_params)
    total_kk = cursor.fetchone()[0]

    # 3. Agama (hanya admin & kepala dusun)
    if current_user.role in ['admin', 'kepala_dusun']:
        agama_query = "SELECT agama, COUNT(*) as jumlah FROM penduduk"
        if base_where:
            agama_query += " WHERE " + base_where
        agama_query += " GROUP BY agama ORDER BY jumlah DESC"
        cursor.execute(agama_query, params)
        agama_data = cursor.fetchall()
    else:
        agama_data = []

    # 4. Pendidikan (hanya admin & kepala dusun)
    if current_user.role in ['admin', 'kepala_dusun']:
        pendidikan_query = "SELECT pendidikan, COUNT(*) as jumlah FROM penduduk"
        if base_where:
            pendidikan_query += " WHERE " + base_where
        pendidikan_query += " GROUP BY pendidikan ORDER BY jumlah DESC"
        cursor.execute(pendidikan_query, params)
        pendidikan_data = cursor.fetchall()
    else:
        pendidikan_data = []

    # 5. Dusun Detail (hanya untuk admin)
    if current_user.role == 'admin':
        cursor.execute("""
            SELECT 
                dusun,
                COUNT(*) as jiwa,
                SUM(CASE WHEN jenis_kelamin = 'L' THEN 1 ELSE 0 END) as laki,
                SUM(CASE WHEN jenis_kelamin = 'P' THEN 1 ELSE 0 END) as perempuan
            FROM penduduk 
            WHERE dusun IS NOT NULL AND TRIM(dusun) != ''
            GROUP BY dusun 
            ORDER BY dusun
        """)
        dusun_data = cursor.fetchall()

        cursor.execute("""
            SELECT dusun, COUNT(DISTINCT nomor_kk) as kk 
            FROM penduduk 
            WHERE nomor_kk IS NOT NULL AND TRIM(nomor_kk) != '' 
              AND dusun IS NOT NULL AND TRIM(dusun) != ''
            GROUP BY dusun 
            ORDER BY dusun
        """)
        kk_per_dusun = cursor.fetchall()

        dusun_summary = {}
        for row in dusun_data:
            dusun_summary[row['dusun']] = {
                'jiwa': row['jiwa'],
                'laki': row['laki'],
                'perempuan': row['perempuan']
            }
        for row in kk_per_dusun:
            dusun_summary[row['dusun']]['kk'] = row['kk']
    else:
        dusun_summary = {}

    conn.close()

    return render_template('statistik.html',
        total_jiwa=total_jiwa,
        total_kk=total_kk,
        agama_data=agama_data,
        pendidikan_data=pendidikan_data,
        dusun_summary=dusun_summary,
        user_role=current_user.role
    )
    
    
# --- TAMBAH USER (ADMIN SAJA) ---
@app.route('/tambah/user', methods=['GET', 'POST'])
@login_required
def tambah_user():
    if current_user.role != 'admin':
        flash("Akses ditolak.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        dusun = request.form.get('dusun') if role == 'kepala_dusun' else None
        nik_masyarakat = request.form.get('nik_masyarakat') if role == 'masyarakat' else None

        conn = get_db()
        try:
            conn.execute('''
                INSERT INTO user (username, password, role, dusun, nik_masyarakat)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, password, role, dusun, nik_masyarakat))
            conn.commit()
            flash("User berhasil ditambahkan!", "success")
            load_users_from_db()
        except sqlite3.IntegrityError:
            flash("Username sudah ada.", "danger")
        finally:
            conn.close()
        return redirect(url_for('index'))

    return render_template('tambah_user.html')
    

def create_charts(dusun_data, agama_data, pendidikan_data, pertumbuhan_data):
    # Hapus grafik lama
    chart_dir = 'static/charts'
    if not os.path.exists(chart_dir):
        os.makedirs(chart_dir)
    
    for f in os.listdir(chart_dir):
        if f.startswith('chart_'):
            os.remove(os.path.join(chart_dir, f))

    # 1. Bar Chart: Jiwa per Dusun
    if dusun_data:
        plt.figure(figsize=(8, 5))
        dusun = [row['dusun'] for row in dusun_data]
        jumlah = [row['jumlah'] for row in dusun_data]
        plt.bar(dusun, jumlah, color='skyblue')
        plt.title('Jumlah Jiwa per Dusun')
        plt.xlabel('Dusun')
        plt.ylabel('Jumlah Jiwa')
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig('static/charts/chart_dusun.png')
        plt.close()

    # 2. Pie Chart: Agama
    if agama_data:
        plt.figure(figsize=(8, 6))
        agama = [row['agama'] for row in agama_data]
        jumlah = [row['jumlah'] for row in agama_data]
        plt.pie(jumlah, labels=agama, autopct='%1.1f%%', startangle=90)
        plt.title('Persentase Agama')
        plt.axis('equal')
        plt.tight_layout()
        plt.savefig('static/charts/chart_agama.png')
        plt.close()

    # 3. Bar Chart: Pendidikan
    if pendidikan_data:
        plt.figure(figsize=(10, 5))
        pendidikan = [row['pendidikan'] for row in pendidikan_data]
        jumlah = [row['jumlah'] for row in pendidikan_data]
        plt.bar(pendidikan, jumlah, color='lightgreen')
        plt.title('Pendidikan Terakhir Penduduk')
        plt.xlabel('Pendidikan')
        plt.ylabel('Jumlah')
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig('static/charts/chart_pendidikan.png')
        plt.close()

    # 4. Line Chart: Pertumbuhan
    if pertumbuhan_data:
        plt.figure(figsize=(10, 5))
        bulan = [row['bulan'] for row in pertumbuhan_data]
        jumlah = [row['jumlah'] for row in pertumbuhan_data]
        plt.plot(bulan, jumlah, marker='o', color='orange')
        plt.title('Pertumbuhan Penduduk per Bulan')
        plt.xlabel('Bulan')
        plt.ylabel('Jumlah Penduduk Baru')
        plt.grid(True)
        plt.tight_layout()
        plt.savefig('static/charts/chart_pertumbuhan.png')
        plt.close()

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    cursor = conn.cursor()

    # 1. Jiwa per Dusun
    cursor.execute("""
        SELECT dusun, COUNT(*) as jumlah 
        FROM penduduk 
        WHERE dusun IS NOT NULL AND TRIM(dusun) != ''
        GROUP BY dusun ORDER BY dusun
    """)
    dusun_data = cursor.fetchall()

    # 2. Agama
    cursor.execute("SELECT agama, COUNT(*) as jumlah FROM penduduk GROUP BY agama ORDER BY jumlah DESC")
    agama_data = cursor.fetchall()

    # 3. Pendidikan
    cursor.execute("SELECT pendidikan, COUNT(*) as jumlah FROM penduduk GROUP BY pendidikan ORDER BY jumlah DESC")
    pendidikan_data = cursor.fetchall()

    # 4. Pertumbuhan per Bulan
    cursor.execute("""
        SELECT SUBSTR(tanggal_input, 1, 7) as bulan, COUNT(*) as jumlah 
        FROM penduduk 
        GROUP BY bulan ORDER BY bulan
    """)
    pertumbuhan_data = cursor.fetchall()

    # 🔴 Tambah: total_jiwa
    cursor.execute("SELECT COUNT(*) FROM penduduk")
    total_jiwa = cursor.fetchone()[0]

    conn.close()

    # Buat grafik
    create_charts(dusun_data, agama_data, pendidikan_data, pertumbuhan_data)

    # 🔴 Kirim total_jiwa ke template
    return render_template('dashboard.html',
                         dusun_data=dusun_data,
                         agama_data=agama_data,
                         pendidikan_data=pendidikan_data,
                         pertumbuhan_data=pertumbuhan_data,
                         total_jiwa=total_jiwa)                       
                         

@app.route('/cetak/statistik')
@login_required
def cetak_statistik():
    try:
        conn = get_db()
        cursor = conn.cursor()

        # 1. Total Jiwa & KK
        cursor.execute("SELECT COUNT(*) FROM penduduk")
        total_jiwa = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT nomor_kk) FROM penduduk WHERE nomor_kk IS NOT NULL AND TRIM(nomor_kk) != ''")
        total_kk = cursor.fetchone()[0]

        # 2. Agama
        cursor.execute("SELECT agama, COUNT(*) FROM penduduk GROUP BY agama ORDER BY COUNT(*) DESC")
        agama_data = cursor.fetchall()

        # 3. Dusun
        cursor.execute("""
            SELECT dusun, COUNT(*) as jiwa 
            FROM penduduk 
            WHERE dusun IS NOT NULL AND TRIM(dusun) != ''
            GROUP BY dusun ORDER BY dusun
        """)
        dusun_data = cursor.fetchall()

        conn.close()

        # Buat PDF
        pdf = FPDF(orientation='P', unit='mm', format='A4')
        pdf.add_page()
        pdf.set_font("helvetica", 'B', 16)
        pdf.cell(0, 10, "STATISTIK KEPENDUDUKAN", ln=True, align='C')
        pdf.set_font("helvetica", '', 12)
        pdf.cell(0, 8, "Desa Nagori Bahapal Raya", ln=True, align='C')
        pdf.ln(10)

        # Informasi Umum
        pdf.set_font("helvetica", 'B', 12)
        pdf.cell(0, 8, f"Total Jiwa: {total_jiwa} | Total KK: {total_kk}", ln=True)
        pdf.ln(5)

        # Agama
        pdf.set_font("helvetica", 'B', 12)
        pdf.cell(0, 8, "Berdasarkan Agama:", ln=True)
        pdf.set_font("helvetica", '', 10)
        for agama, count in agama_data:
            pdf.cell(0, 6, f"- {agama}: {count} orang", ln=True)
        pdf.ln(10)

        # Dusun
        pdf.set_font("helvetica", 'B', 12)
        pdf.cell(0, 8, "Berdasarkan Dusun:", ln=True)
        pdf.set_font("helvetica", '', 10)
        for dusun, count in dusun_data:
            pdf.cell(0, 6, f"- Dusun {dusun}: {count} jiwa", ln=True)
        pdf.ln(10)

        # Footer
        pdf.set_font("helvetica", 'I', 10)
        pdf.cell(0, 6, f"Dicetak pada: {datetime.now().strftime('%d-%m-%Y %H:%M')}", ln=True)
        pdf.cell(0, 6, f"Oleh: {current_user.username}", ln=True)

        # Simpan PDF
        os.makedirs("laporan/pdf", exist_ok=True)
        filepath = "laporan/pdf/statistik.pdf"
        pdf.output(filepath)

        # Download file
        return send_file(filepath, as_attachment=True)

    except Exception as e:
        flash(f"Gagal cetak statistik: {str(e)}", "danger")
        return redirect(url_for('statistik'))

@app.route('/ekspor/excel')
@login_required
def ekspor_excel():
    try:
        # Buat folder ekspor jika belum ada
        os.makedirs("ekspor", exist_ok=True)
        
        # Ambil data dari database
        conn = get_db()
        df = pd.read_sql_query("SELECT * FROM penduduk", conn)
        conn.close()

        # Jika tidak ada data
        if df.empty:
            flash("Tidak ada data untuk diekspor.", "warning")
            return redirect(url_for('index'))

        # Bersihkan nama kolom
        df = df.rename(columns={
            'nomor_kk': 'Nomor KK',
            'nik': 'NIK',
            'nama': 'Nama',
            'hubungan': 'Hubungan',
            'jenis_kelamin': 'Jenis Kelamin',
            'tempat_lahir': 'Tempat Lahir',
            'tanggal_lahir': 'Tanggal Lahir',
            'agama': 'Agama',
            'status_perkawinan': 'Status Perkawinan',
            'pendidikan': 'Pendidikan',
            'pekerjaan': 'Pekerjaan',
            'alamat': 'Alamat',
            'rt_rw': 'RT/RW',
            'dusun': 'Dusun',
            'golongan_darah': 'Gol. Darah',
            'kesejahteraan': 'Program Kesejahteraan',
            'tanggal_input': 'Tanggal Input',
            'foto_ktp': 'Foto KTP'
        })

        # Nama file: hindari karakter ilegal
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"data_penduduk_{timestamp}.xlsx"
        filepath = os.path.join('ekspor', filename)

        # Simpan ke Excel
        try:
            df.to_excel(filepath, index=False, sheet_name='Data Penduduk')
        except Exception as e:
            # Jika gagal karena path terlalu panjang
            if "path too long" in str(e).lower() or "cannot save" in str(e).lower():
                flash("Gagal ekspor: Path terlalu panjang. Coba simpan di folder lebih pendek.", "danger")
            else:
                flash(f"Gagal simpan file: {str(e)}", "danger")
            return redirect(url_for('index'))

        # Download file
        return send_file(filepath, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except Exception as e:
        flash(f"Error saat ekspor: {str(e)}", "danger")
        return redirect(url_for('index'))
        
        
import re

def validasi_data(nama, nik, nomor_kk, dusun):
    errors = []

    # Nama: hanya huruf dan spasi, kapital
    if not re.match(r'^[A-Z\s]+$', nama):
        errors.append("Nama hanya boleh huruf kapital dan spasi.")

    # NIK: harus 16 digit angka
    if not re.match(r'^\d{16}$', nik):
        errors.append("NIK harus 16 digit angka.")

    # Nomor KK: harus 16 digit angka
    if not re.match(r'^\d{16}$', nomor_kk):
        errors.append("Nomor KK harus 16 digit angka.")

    # Dusun: hanya boleh SATU, DUA, TIGA, EMPAT
    if dusun not in ['SATU', 'DUA', 'TIGA', 'EMPAT']:
        errors.append("Pilih satu dusun yang valid.")

    return errors
    
    
@app.route('/progress')
@login_required
def progress():
    if current_user.role != 'admin':
        flash("Akses ditolak. Hanya admin yang bisa melihat progress.", "danger")
        return redirect(url_for('index'))

    conn = get_db()
    cursor = conn.cursor()

    # 1. Target penduduk per dusun (sesuaikan dengan kondisi desa)
    target_dusun = {
        'SATU': 150,
        'DUA': 120,
        'TIGA': 130,
        'EMPAT': 140
    }

    # 2. Progress per Dusun
    cursor.execute("""
        SELECT dusun, COUNT(*) as jumlah 
        FROM penduduk 
        WHERE dusun IS NOT NULL AND TRIM(dusun) != ''
        GROUP BY dusun
    """)
    data_dusun = cursor.fetchall()

    progress_data = []
    total_target = 0
    total_terinput = 0

    for dusun, jumlah in data_dusun:
        target = target_dusun.get(dusun, 100)
        persen = min(100, round((jumlah / target) * 100))

        progress_data.append({
            'dusun': dusun,
            'terinput': jumlah,
            'target': target,
            'persen': persen
        })

        total_terinput += jumlah
        total_target += target

    total_persen = min(100, round((total_terinput / total_target) * 100)) if total_target > 0 else 0

    # 3. Jumlah input per role user
    cursor.execute("""
        SELECT u.role, COUNT(p.nik) as jumlah
        FROM penduduk p
        JOIN user u ON p.dusun = u.dusun OR p.nik = u.nik_masyarakat
        GROUP BY u.role
    """)
    data_per_role = cursor.fetchall()

    conn.close()

    return render_template('progress.html',
                         progress_data=progress_data,
                         total_terinput=total_terinput,
                         total_target=total_target,
                         total_persen=total_persen,
                         data_per_role=data_per_role)
                         
@app.route('/hapus/<nik>', methods=['GET', 'POST'])
@login_required
def hapus(nik):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT nama, dusun FROM penduduk WHERE nik = ?", (nik,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        flash("Data tidak ditemukan.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Ambil alasan dari form
        alasan = request.form.get('alasan', '').strip()
        if not alasan:
            flash("Alasan penghapusan wajib dipilih.", "danger")
            return redirect(url_for('index'))

        try:
            conn = get_db()
            # Simpan ke log penghapusan
            conn.execute('''INSERT INTO log_penghapusan (nik, nama, alasan_hapus, dusun, dihapus_oleh)
                            VALUES (?, ?, ?, ?, ?)''', 
                         (nik, row['nama'], alasan, row['dusun'], current_user.username))
            
            # Hapus dari penduduk
            conn.execute("DELETE FROM penduduk WHERE nik = ?", (nik,))
            conn.commit()
            flash(f"Data {row['nama']} berhasil dihapus.", "success")
        except Exception as e:
            flash(f"Gagal hapus data: {str(e)}", "danger")
        finally:
            conn.close()

        return redirect(url_for('index'))

    # Jika method GET (untuk keamanan)
    # Anda bisa redirect atau tampilkan konfirmasi
    flash("Gunakan form untuk menghapus data.", "warning")
    return redirect(url_for('index'))    
    
    
@app.route('/riwayat_hapus')
@login_required
def riwayat_hapus():
    if current_user.role != 'admin':
        flash("Akses ditolak.", "danger")
        return redirect(url_for('index'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM log_penghapusan ORDER BY tanggal_hapus DESC")
    riwayat = cursor.fetchall()
    conn.close()

    return render_template('riwayat_hapus.html', riwayat=riwayat)
    
    
        
# --- ERROR HANDLER ---
@app.errorhandler(404)
def not_found(error):
    return render_template('error.html', message="Halaman tidak ditemukan. Mungkin Anda belum login atau halaman tidak tersedia."), 404

@app.errorhandler(500)
def server_error(error):
    return render_template('error.html', message="Terjadi kesalahan internal. Silakan cek log aplikasi."), 500

# --- JALANKAN APLIKASI ---
if __name__ == '__main__':
    start_backup_scheduler()
    app.run(debug=True, host='0.0.0.0', port=5000)