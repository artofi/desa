# app.py
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
import matplotlib
matplotlib.use('Agg')  # Penting: agar jalan di web server
import matplotlib.pyplot as plt

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

# --- FUNGSI BANTUAN ---
def get_db():
    conn = sqlite3.connect('desa.db')
    conn.row_factory = sqlite3.Row
    return conn

def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', filename)

def shrink_font_for_fit(pdf, text, max_width, original_size, min_size=6):
    """
    Perkecil ukuran font sampai teks muat dalam lebar kolom.
    Digunakan agar nama panjang tidak memicu multi_cell (yang bikin jelek).
    """
    pdf.set_font("helvetica", '', original_size)
    while pdf.get_string_width(text) > max_width and pdf.font_size > min_size:
        pdf.set_font("helvetica", '', pdf.font_size - 0.5)
    return pdf.font_size

# --- INISIALISASI DATABASE ---
def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS penduduk (
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
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        dusun TEXT,
        nik_masyarakat TEXT
    )''')
    conn.commit()
    conn.close()

def init_log_table():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS log_penghapusan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nik TEXT NOT NULL,
        nama TEXT NOT NULL,
        alasan_hapus TEXT,
        dusun TEXT,
        tanggal_hapus DATETIME DEFAULT CURRENT_TIMESTAMP,
        dihapus_oleh TEXT
    )""")
    conn.commit()
    conn.close()

def init_audit_log():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS log_aktivitas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        aksi TEXT NOT NULL,
        detail TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

def catat_aktivitas(username, aksi, detail=""):
    """
    Catat aktivitas user ke log_audit
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO log_aktivitas (username, aksi, detail)
                          VALUES (?, ?, ?)''', (username, aksi, detail))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error mencatat aktivitas: {str(e)}")

# --- INISIALISASI DATABASE & USER AWAL ---
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

# Inisialisasi tabel log
init_log_table()
init_audit_log()  # ✅ Harus dipanggil setelah definisi fungsi

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

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
def load_users_from_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, password, role, dusun, nik_masyarakat FROM user")
    rows = cursor.fetchall()
    conn.close()
    
    global users
    users.clear()
    for row in rows:
        users[row['username']] = User(
            id=row['username'],
            username=row['username'],
            role=row['role'],
            dusun=row['dusun'],
            nik_masyarakat=row['nik_masyarakat']
        )

@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)

# Muat user dari database
load_users_from_db()


def catat_aktivitas(username, aksi, detail=""):
    """
    Catat aktivitas user ke log_audit
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO log_aktivitas (username, aksi, detail)
                          VALUES (?, ?, ?)''', (username, aksi, detail))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error mencatat aktivitas: {str(e)}")
        


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
    
    # Pagination
    try:
        limit = int(request.args.get('limit', 50))
        if limit not in [50, 100, 500]:
            limit = 50
    except:
        limit = 50
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except:
        page = 1
    offset = (page - 1) * limit

    # Variabel default
    total_jiwa = total_kk = total_dusun = 0
    rows = []
    total_pages = 1  # ✅ Default 1

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
            count_query = "SELECT COUNT(*) FROM penduduk"
            params = ()
            count_params = ()

            # Filter role
            if current_user.role == 'kepala_dusun':
                base_query += " WHERE dusun = ?"
                count_query += " WHERE dusun = ?"
                params = (current_user.dusun,)
                count_params = (current_user.dusun,)
            elif current_user.role == 'masyarakat':
                base_query += " WHERE nik = ?"
                count_query += " WHERE nik = ?"
                params = (current_user.nik_masyarakat,)
                count_params = (current_user.nik_masyarakat,)

            # Pencarian
            if search_query:
                search_param = f'%{search_query}%'
                where_clause = " (nomor_kk LIKE ? OR nik LIKE ? OR nama LIKE ?)"
                if "WHERE" in base_query:
                    base_query += " AND" + where_clause
                    count_query += " AND" + where_clause
                else:
                    base_query += " WHERE" + where_clause
                    count_query += " WHERE" + where_clause
                search_values = (search_param, search_param, search_param)
                params += search_values
                count_params += search_values

            # Hitung total halaman
            if limit != 'all':
                cursor.execute(count_query, count_params)
                total_count = cursor.fetchone()[0]
                total_pages = (total_count + limit - 1) // limit
            else:
                total_pages = 1  # ✅ Tetap kirim 1 jika 'all'

            # Urutkan
            if view_mode == 'nik':
                order_by = " ORDER BY nama"
            else:
                order_by = " ORDER BY nomor_kk, CASE WHEN hubungan='Kepala Keluarga' THEN 0 ELSE 1 END, nama"

            # Tambah LIMIT dan OFFSET hanya jika tidak "all"
            if limit != 'all':
                order_by += " LIMIT ? OFFSET ?"
                params += (limit, offset)

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
                             total_dusun=total_dusun,
                             limit=limit,
                             page=page,
                             total_pages=total_pages)  # ✅ Dikirim
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
                             total_dusun=total_dusun,
                             limit=limit,
                             page=page,
                             total_pages=total_pages)  # ✅ Dikirim
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

@app.route('/tambah', methods=['GET', 'POST'])
@login_required
def tambah():
    programs = ["BPJS KIS", "BPJS Mandiri", "PKH", "Sembako", "PIP", "BLT", "Tidak Ada"]
    if request.method == 'POST':
        nama = request.form['nama'].strip().upper()
        nik = request.form['nik'].strip()
        nomor_kk = request.form['nomor_kk'].strip()
        dusun = request.form.get('dusun', '').strip()

        # 🔧 1. Tambah validasi role
        if current_user.role == 'kepala_dusun' and dusun != current_user.dusun:
            flash("Anda hanya bisa input data di dusun Anda.", "danger")
            return redirect(url_for('tambah'))
        elif current_user.role == 'masyarakat':
            flash("Anda tidak diizinkan menambah data.", "danger")
            return redirect(url_for('index'))

        # 🔧 2. Validasi data
        errors = validasi_data(nama, nik, nomor_kk, dusun)
        if errors:
            for e in errors:
                flash(e, "danger")
            return redirect(url_for('tambah'))

        # 🔧 3. Cek apakah NIK atau KK sudah ada
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM penduduk WHERE nik = ?", (nik,))
        if cursor.fetchone()[0] > 0:
            flash("NIK sudah ada di database.", "danger")
            conn.close()
            return redirect(url_for('tambah'))

        cursor.execute("SELECT COUNT(*) FROM penduduk WHERE nomor_kk = ? AND nik != ?", (nomor_kk, nik))
        if cursor.fetchone()[0] > 0 and hubungan != 'Kepala Keluarga':
            flash("Nomor KK sudah digunakan oleh kepala keluarga lain.", "warning")

        # 🔧 4. Sanitasi nama (hapus <br>, line break, karakter aneh)
        nama = re.sub(r'<br>|<br/>|\n|\r', ' ', nama)  # Ganti <br> dengan spasi
        nama = re.sub(r'\s+', ' ', nama).strip()      # Hapus spasi ganda

        # 🔧 5. Simpan data
        data = {
            'nomor_kk': nomor_kk,
            'nik': nik,
            'nama': nama,
            'hubungan': request.form['hubungan'],
            'jenis_kelamin': request.form['jenis_kelamin'],
            'tempat_lahir': request.form['tempat_lahir'].strip().title(),
            'tanggal_lahir': request.form['tanggal_lahir'],
            'agama': request.form['agama'],
            'status_perkawinan': request.form['status_perkawinan'],
            'pendidikan': request.form['pendidikan'],
            'pekerjaan': request.form['pekerjaan'].strip().title(),
            'alamat': request.form['alamat'].strip().upper(),
            'rt_rw': request.form['rt_rw'].strip(),
            'dusun': dusun,
            'golongan_darah': request.form['golongan_darah'],
            'kesejahteraan': ', '.join(request.form.getlist('kesejahteraan')),
            'tanggal_input': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'foto_ktp': ''
        }

        try:
            conn.execute('''
                INSERT INTO penduduk (nomor_kk, nik, nama, hubungan, jenis_kelamin, tempat_lahir, tanggal_lahir, 
                agama, status_perkawinan, pendidikan, pekerjaan, alamat, rt_rw, dusun, golongan_darah, kesejahteraan, tanggal_input, foto_ktp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', tuple(data.values()))
            conn.commit()
            flash("Data berhasil ditambahkan!", "success")
        except sqlite3.IntegrityError as e:
            flash(f"Gagal simpan data: {str(e)}", "danger")
        finally:
            conn.close()
        return redirect(url_for('index'))
    
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
    
    # Base query
    base_query = """
        SELECT * FROM penduduk 
        WHERE nomor_kk = ? 
        ORDER BY CASE WHEN hubungan='Kepala Keluarga' THEN 0 ELSE 1 END, nama
    """
    params = (nomor_kk,)
    
    if current_user.role == 'kepala_dusun':
        base_query = base_query.replace("WHERE", "WHERE dusun = ? AND")
        params = (current_user.dusun, nomor_kk)
    elif current_user.role == 'masyarakat':
        base_query = base_query.replace("WHERE", "WHERE nik = ? AND")
        params = (current_user.nik_masyarakat, nomor_kk)
    
    cursor.execute(base_query, params)
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        flash("Data tidak ditemukan untuk nomor KK ini.", "warning")
        return redirect(url_for('index'))

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # Background watermark
    pdf.set_text_color(230, 230, 230)
    pdf.set_font("helvetica", 'B', 80)
    pdf.text(30, 100, "NAGORI BAHAPAL RAYA")
    pdf.set_text_color(0, 0, 0)

    # Logo
    try:
        pdf.image('static/img/logo_desa.png', x=10, y=10, w=20)
    except:
        pass

    # Header
    pdf.set_font("helvetica", 'B', 18)
    pdf.cell(0, 10, "KARTU KELUARGA", ln=True, align='C')
    pdf.set_font("helvetica", '', 14)
    pdf.cell(0, 8, f"No. KK: {nomor_kk}", ln=True, align='C')
    pdf.ln(10)

    # Garis pemisah
    pdf.set_draw_color(0, 0, 0)
    pdf.line(10, 40, 290, 40)
    pdf.ln(5)

    # Tabel
    pdf.set_font("helvetica", 'B', 9)
    col_widths = [10, 28, 35, 18, 25, 25, 18, 20, 20, 25, 20, 20]  # Tambah kolom No.
    headers = ["No", "NIK", "Nama", "JK", "Tmpt Lahir", "Tgl Lahir", "Agama", "Status", "Pendidikan", "Pekerjaan", "Gol. Darah", "Hubungan"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, 1, 0, 'C')
    pdf.ln(8)

    pdf.set_font("helvetica", '', 8)
    for idx, row in enumerate(rows, 1):
        x_before = pdf.get_x()
        y_before = pdf.get_y()
        
        # Kolom 1: No
        pdf.cell(col_widths[0], 8, str(idx), 1, 0, 'C')
        
        # Kolom 2: NIK
        pdf.cell(col_widths[1], 8, str(row['nik']), 1, 0, 'L')
        
        # Kolom 3: Nama
        max_width = col_widths[2] - 2
        shrink_font_for_fit(pdf, row['nama'], max_width, 8, 6)
        pdf.cell(col_widths[2], 8, row['nama'], 1, 0, 'L')
        pdf.set_font("helvetica", '', 8)

        # Kolom 4: JK
        pdf.cell(col_widths[3], 8, row['jenis_kelamin'], 1, 0, 'C')
        # Kolom 5: Tempat Lahir
        shrink_font_for_fit(pdf, row['tempat_lahir'], col_widths[4] - 2, 8, 6)
        pdf.cell(col_widths[4], 8, row['tempat_lahir'], 1, 0, 'L')
        pdf.set_font("helvetica", '', 8)
        # Kolom 6: Tanggal Lahir
        pdf.cell(col_widths[5], 8, row['tanggal_lahir'], 1, 0, 'L')
        # Kolom 7: Agama
        pdf.cell(col_widths[6], 8, row['agama'], 1, 0, 'L')
        # Kolom 8: Status
        pdf.cell(col_widths[7], 8, row['status_perkawinan'], 1, 0, 'L')
        # Kolom 9: Pendidikan
        pdf.cell(col_widths[8], 8, row['pendidikan'], 1, 0, 'L')
        # Kolom 10: Pekerjaan
        shrink_font_for_fit(pdf, row['pekerjaan'], col_widths[9] - 2, 8, 6)
        pdf.cell(col_widths[9], 8, row['pekerjaan'], 1, 0, 'L')
        pdf.set_font("helvetica", '', 8)
        # Kolom 11: Gol. Darah
        pdf.cell(col_widths[10], 8, row['golongan_darah'], 1, 0, 'C')
        # Kolom 12: Hubungan
        pdf.cell(col_widths[11], 8, row['hubungan'], 1, 0, 'L')

        pdf.ln(8)

    # Total Anggota
    pdf.set_font("helvetica", 'B', 8)
    pdf.cell(col_widths[0] + col_widths[1], 8, f"Total Anggota: {len(rows)}", 1, 0, 'C')
    pdf.cell(sum(col_widths[2:]), 8, "", 1)  # Gabungkan sisa kolom
    pdf.ln(10)

    # Footer
    pdf.set_font("helvetica", 'I', 8)
    pdf.cell(0, 6, f"Dicetak oleh: {current_user.username} | Tanggal: {datetime.now().strftime('%d-%m-%Y %H:%M')}", 0, 1, 'C')

    os.makedirs("laporan/pdf", exist_ok=True)
    safe_kk = sanitize_filename(nomor_kk)
    filename = os.path.join("laporan", "pdf", f"kk_{safe_kk}.pdf")
    pdf.output(filename)
    return send_file(filename, as_attachment=True)
    
# --- CETAK SEMUA KK ---
@app.route('/cetak/semua/kk')
@login_required
def cetak_semua_kk():
    # Filter role
    base_query = """
        SELECT DISTINCT nomor_kk FROM penduduk 
        WHERE nomor_kk IS NOT NULL AND TRIM(nomor_kk) != ''
    """
    params = ()
    
    if current_user.role == 'kepala_dusun':
        base_query += " AND dusun = ?"
        params = (current_user.dusun,)
    elif current_user.role == 'masyarakat':
        base_query += " AND nik = ?"
        params = (current_user.nik_masyarakat,)

    base_query += " ORDER BY nomor_kk"
    
    conn = get_db()
    kk_rows = conn.execute(base_query, params).fetchall()
    conn.close()

    kks = [row['nomor_kk'] for row in kk_rows]
    if not kks:
        flash("Tidak ada data KK untuk dicetak.", "info")
        return redirect(url_for('index'))

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)

    for nomor_kk in kks:
        conn = get_db()
        rows = conn.execute("""
            SELECT * FROM penduduk 
            WHERE nomor_kk = ? 
            ORDER BY CASE WHEN hubungan='Kepala Keluarga' THEN 0 ELSE 1 END, nama
        """, (nomor_kk,)).fetchall()
        conn.close()

        if not rows:
            continue

        pdf.add_page()
        
        # Background watermark
        pdf.set_text_color(230, 230, 230)
        pdf.set_font("helvetica", 'B', 80)
        pdf.text(30, 100, "NAGORI BAHAPAL RAYA")
        pdf.set_text_color(0, 0, 0)

        # Logo
        try:
            pdf.image('static/img/logo_desa.png', x=10, y=10, w=20)
        except:
            pass

        # Header
        pdf.set_font("helvetica", 'B', 18)
        pdf.cell(0, 10, "KARTU KELUARGA", ln=True, align='C')
        pdf.set_font("helvetica", '', 14)
        pdf.cell(0, 8, f"No. KK: {nomor_kk}", ln=True, align='C')
        pdf.ln(10)

        # Garis pemisah
        pdf.set_draw_color(0, 0, 0)
        pdf.line(10, 40, 290, 40)
        pdf.ln(5)

        # Tabel
        pdf.set_font("helvetica", 'B', 9)
        col_widths = [28, 35, 18, 25, 25, 18, 20, 20, 25, 20, 20]
        headers = ["NIK", "Nama", "JK", "Tmpt Lahir", "Tgl Lahir", "Agama", "Status", "Pendidikan", "Pekerjaan", "Gol. Darah", "Hubungan"]
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 8, h, 1, 0, 'C')
        pdf.ln(8)

        pdf.set_font("helvetica", '', 8)
        for row in rows:
            x_before = pdf.get_x()
            y_before = pdf.get_y()
            
            # Kolom 1: NIK
            pdf.cell(col_widths[0], 8, str(row['nik']), 1, 0, 'L')
            
            # Kolom 2: Nama (font mengecil otomatis)
            max_width = col_widths[1] - 2
            shrink_font_for_fit(pdf, row['nama'], max_width, 8, 6)
            pdf.cell(col_widths[1], 8, row['nama'], 1, 0, 'L')
            # Reset font ke 8
            pdf.set_font("helvetica", '', 8)

            # Kolom 3: JK
            pdf.cell(col_widths[2], 8, row['jenis_kelamin'], 1, 0, 'C')
            # Kolom 4: Tempat Lahir
            shrink_font_for_fit(pdf, row['tempat_lahir'], col_widths[3] - 2, 8, 6)
            pdf.cell(col_widths[3], 8, row['tempat_lahir'], 1, 0, 'L')
            pdf.set_font("helvetica", '', 8)
            # Kolom 5: Tanggal Lahir
            pdf.cell(col_widths[4], 8, row['tanggal_lahir'], 1, 0, 'L')
            # Kolom 6: Agama
            pdf.cell(col_widths[5], 8, row['agama'], 1, 0, 'L')
            # Kolom 7: Status
            pdf.cell(col_widths[6], 8, row['status_perkawinan'], 1, 0, 'L')
            # Kolom 8: Pendidikan
            pdf.cell(col_widths[7], 8, row['pendidikan'], 1, 0, 'L')
            # Kolom 9: Pekerjaan
            shrink_font_for_fit(pdf, row['pekerjaan'], col_widths[8] - 2, 8, 6)
            pdf.cell(col_widths[8], 8, row['pekerjaan'], 1, 0, 'L')
            pdf.set_font("helvetica", '', 8)
            # Kolom 10: Gol. Darah
            pdf.cell(col_widths[9], 8, row['golongan_darah'], 1, 0, 'C')
            # Kolom 11: Hubungan
            pdf.cell(col_widths[10], 8, row['hubungan'], 1, 0, 'L')

            # Pindah baris
            pdf.ln(8)

        # Footer
        pdf.ln(10)
        pdf.set_font("helvetica", 'I', 8)
        pdf.cell(0, 6, f"Dicetak oleh: {current_user.username} | Tanggal: {datetime.now().strftime('%d-%m-%Y %H:%M')}", 0, 1, 'C')

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
        
        # Validasi NIK
        if not nik:
            flash("NIK tidak boleh kosong.", "danger")
            return redirect(url_for('cetak_kk_dari_nik'))
            
        if not re.match(r'^\d{16}$', nik):
            flash("NIK harus 16 digit angka.", "danger")
            return redirect(url_for('cetak_kk_dari_nik'))

        conn = get_db()
        cursor = conn.cursor()
        
        # Base query
        base_query = "SELECT nomor_kk FROM penduduk WHERE nik = ?"
        params = (nik,)
        
        # Filter role
        if current_user.role == 'kepala_dusun':
            base_query += " AND dusun = ?"
            params = (nik, current_user.dusun)
        elif current_user.role == 'masyarakat':
            base_query += " AND nik = ?"
            params = (nik, current_user.nik_masyarakat)
        
        cursor.execute(base_query, params)
        result = cursor.fetchone()
        conn.close()

        if not result:
            flash("NIK tidak ditemukan atau Anda tidak berhak mengakses data ini.", "danger")
            return redirect(url_for('cetak_kk_dari_nik'))

        nomor_kk = result['nomor_kk']
        if not nomor_kk or not nomor_kk.strip():
            flash("NIK ini tidak terdaftar sebagai anggota keluarga.", "warning")
            return redirect(url_for('cetak_kk_dari_nik'))

        return redirect(url_for('cetak_kk', nomor_kk=nomor_kk))

    return render_template('cetak_kk_dari_nik.html')

# --- CETAK LAPORAN (PILIHAN) ---
@app.route('/cetak')
@login_required
def cetak_pilihan():
    conn = get_db()
    cursor = conn.cursor()
    
    base_query = "SELECT DISTINCT dusun FROM penduduk WHERE dusun IS NOT NULL AND TRIM(dusun) != ''"
    params = ()
    
    if current_user.role == 'kepala_dusun':
        base_query += " AND dusun = ?"
        params = (current_user.dusun,)
    elif current_user.role == 'masyarakat':
        base_query += " AND nik = ?"
        params = (current_user.nik_masyarakat,)
    
    base_query += " ORDER BY dusun"
    
    cursor.execute(base_query, params)
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
    
    # Background watermark
    pdf.set_text_color(230, 230, 230)
    pdf.set_font("helvetica", 'B', 80)
    pdf.text(30, 100, "NAGORI BAHAPAL RAYA")
    pdf.set_text_color(0, 0, 0)

    # Logo
    try:
        pdf.image('static/img/logo_desa.png', x=10, y=10, w=20)
    except:
        pass

    # Header
    pdf.set_font("helvetica", 'B', 16)
    pdf.cell(0, 10, "DAFTAR SEMUA PENDUDUK", ln=True, align='C')
    pdf.set_font("helvetica", '', 12)
    pdf.cell(0, 8, "Desa Nagori Bahapal Raya", ln=True, align='C')
    pdf.ln(10)

    # Tabel
    pdf.set_font("helvetica", 'B', 8)
    col_widths = [10, 25, 28, 35, 25, 18, 20, 20, 25, 25, 30]
    headers = ["No", "No. KK", "NIK", "Nama", "Hubungan", "JK", "Pendidikan", "Pekerjaan", "Dusun", "Alamat", "Kesejahteraan"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, 1, 0, 'C')
    pdf.ln(8)

    pdf.set_font("helvetica", '', 7)
    for idx, row in enumerate(rows, 1):
        # Kolom 1: No
        pdf.cell(col_widths[0], 8, str(idx), 1, 0, 'C')
        # Kolom 2: No. KK
        pdf.cell(col_widths[1], 8, str(row['nomor_kk'] or '-'), 1)
        # Kolom 3: NIK
        pdf.cell(col_widths[2], 8, str(row['nik']), 1)
        # Kolom 4: Nama
        shrink_font_for_fit(pdf, row['nama'], col_widths[3] - 2, 7, 6)
        pdf.cell(col_widths[3], 8, row['nama'], 1)
        pdf.set_font("helvetica", '', 7)
        # Kolom 5: Hubungan
        pdf.cell(col_widths[4], 8, str(row['hubungan'] or '-'), 1)
        # Kolom 6: JK
        pdf.cell(col_widths[5], 8, str(row['jenis_kelamin'] or '-'), 1)
        # Kolom 7: Pendidikan
        pdf.cell(col_widths[6], 8, str(row['pendidikan'] or '-'), 1)
        # Kolom 8: Pekerjaan
        shrink_font_for_fit(pdf, row['pekerjaan'] or '-', col_widths[7] - 2, 7, 6)
        pdf.cell(col_widths[7], 8, str(row['pekerjaan'] or '-'), 1)
        pdf.set_font("helvetica", '', 7)
        # Kolom 9: Dusun
        pdf.cell(col_widths[8], 8, str(row['dusun']), 1)
        # Kolom 10: Alamat
        shrink_font_for_fit(pdf, row['alamat'] or '-', col_widths[9] - 2, 7, 6)
        pdf.cell(col_widths[9], 8, str(row['alamat'] or '-'), 1)
        pdf.set_font("helvetica", '', 7)
        # Kolom 11: Kesejahteraan
        kesejahteraan = row['kesejahteraan'].replace(',', ', ') if row['kesejahteraan'] else '-'
        shrink_font_for_fit(pdf, kesejahteraan, col_widths[10] - 2, 7, 6)
        pdf.cell(col_widths[10], 8, kesejahteraan, 1)
        pdf.set_font("helvetica", '', 7)
        pdf.ln(8)

    # Total Penduduk
    pdf.set_font("helvetica", 'B', 8)
    pdf.cell(col_widths[0] + sum(col_widths[1:4]), 8, f"TOTAL PENDUDUK: {len(rows)}", 1, 0, 'C')
    pdf.cell(sum(col_widths[4:]), 8, "", 1)  # Gabungkan sisa kolom
    pdf.ln(10)

    # Footer
    pdf.set_font("helvetica", 'I', 8)
    pdf.cell(0, 6, f"Dicetak oleh: {current_user.username} | Tanggal: {datetime.now().strftime('%d-%m-%Y %H:%M')}", 0, 1, 'C')

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
        
    valid_dusun = ['SATU', 'DUA', 'TIGA', 'EMPAT']
    if dusun not in valid_dusun:
        flash("Dusun tidak ditemukan.", "danger")
        return redirect(url_for('cetak_pilihan'))

    # Base query
    base_query = """
        SELECT nomor_kk, nik, nama, hubungan, jenis_kelamin, 
               pendidikan, pekerjaan, alamat, kesejahteraan 
        FROM penduduk 
        WHERE dusun = ? 
        ORDER BY nomor_kk, 
                 CASE WHEN hubungan = 'Kepala Keluarga' THEN 0 ELSE 1 END, 
                 nama
    """
    params = (dusun,)
    
    if current_user.role == 'kepala_dusun' and current_user.dusun != dusun:
        flash("Anda hanya bisa cetak daftar di dusun Anda.", "danger")
        return redirect(url_for('cetak_pilihan'))
    elif current_user.role == 'masyarakat':
        flash("Anda tidak diizinkan mengakses fitur ini.", "danger")
        return redirect(url_for('index'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(base_query, params)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        flash(f"Tidak ada data di Dusun {dusun}.", "info")
        return redirect(url_for('cetak_pilihan'))

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # Background watermark
    pdf.set_text_color(230, 230, 230)
    pdf.set_font("helvetica", 'B', 80)
    pdf.text(30, 100, "NAGORI BAHAPAL RAYA")
    pdf.set_text_color(0, 0, 0)

    # Logo
    try:
        pdf.image('static/img/logo_desa.png', x=10, y=10, w=20)
    except:
        pass

    # Header
    pdf.set_font("helvetica", 'B', 16)
    pdf.cell(0, 10, f"DAFTAR PENDUDUK DUSUN {dusun.upper()}", ln=True, align='C')
    pdf.ln(10)

    # Tabel
    pdf.set_font("helvetica", 'B', 8)
    col_widths = [10, 25, 28, 35, 25, 18, 20, 20, 25, 30]
    headers = ["No", "No. KK", "NIK", "Nama", "Hubungan", "JK", "Pendidikan", "Pekerjaan", "Alamat", "Kesejahteraan"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, 1, 0, 'C')
    pdf.ln(8)

    pdf.set_font("helvetica", '', 7)
    for idx, row in enumerate(rows, 1):
        # Kolom 1: No
        pdf.cell(col_widths[0], 8, str(idx), 1, 0, 'C')
        # Kolom 2: No. KK
        pdf.cell(col_widths[1], 8, str(row['nomor_kk'] or '-'), 1)
        # Kolom 3: NIK
        pdf.cell(col_widths[2], 8, str(row['nik']), 1)
        # Kolom 4: Nama
        shrink_font_for_fit(pdf, row['nama'], col_widths[3] - 2, 7, 6)
        pdf.cell(col_widths[3], 8, row['nama'], 1)
        pdf.set_font("helvetica", '', 7)
        # Kolom 5: Hubungan
        pdf.cell(col_widths[4], 8, str(row['hubungan'] or '-'), 1)
        # Kolom 6: JK
        pdf.cell(col_widths[5], 8, str(row['jenis_kelamin'] or '-'), 1)
        # Kolom 7: Pendidikan
        pdf.cell(col_widths[6], 8, str(row['pendidikan'] or '-'), 1)
        # Kolom 8: Pekerjaan
        shrink_font_for_fit(pdf, row['pekerjaan'] or '-', col_widths[7] - 2, 7, 6)
        pdf.cell(col_widths[7], 8, str(row['pekerjaan'] or '-'), 1)
        pdf.set_font("helvetica", '', 7)
        # Kolom 9: Alamat
        shrink_font_for_fit(pdf, row['alamat'] or '-', col_widths[8] - 2, 7, 6)
        pdf.cell(col_widths[8], 8, str(row['alamat'] or '-'), 1)
        pdf.set_font("helvetica", '', 7)
        # Kolom 10: Kesejahteraan
        kesejahteraan = row['kesejahteraan'].replace(',', ', ') if row['kesejahteraan'] else '-'
        shrink_font_for_fit(pdf, kesejahteraan, col_widths[9] - 2, 7, 6)
        pdf.cell(col_widths[9], 8, kesejahteraan, 1)
        pdf.set_font("helvetica", '', 7)
        pdf.ln(8)

    # Total Penduduk di Dusun
    pdf.set_font("helvetica", 'B', 8)
    pdf.cell(col_widths[0] + sum(col_widths[1:4]), 8, f"TOTAL: {len(rows)} ORANG", 1, 0, 'C')
    pdf.cell(sum(col_widths[4:]), 8, "", 1)  # Gabungkan sisa kolom
    pdf.ln(10)

    # Footer
    pdf.set_font("helvetica", 'I', 8)
    pdf.cell(0, 6, f"Dicetak oleh: {current_user.username} | Tanggal: {datetime.now().strftime('%d-%m-%Y %H:%M')}", 0, 1, 'C')

    os.makedirs("laporan/pdf", exist_ok=True)
    safe_dusun = sanitize_filename(dusun)
    filename = f"laporan/pdf/daftar_dusun_{safe_dusun}.pdf"
    pdf.output(filename)
    return send_file(filename, as_attachment=True)
 
    
def word_wrap(text, pdf, max_width):
    lines = []
    words = text.split(' ')
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip()
        if pdf.get_string_width(test_line) <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
            while pdf.get_string_width(current_line) > max_width:
                current_line = current_line[:-1]
                if not current_line:
                    break
    if current_line:
        lines.append(current_line)
    return lines 

 
@app.route('/cetak/kk/dusun/<dusun>')
@login_required
def cetak_kk_per_dusun(dusun):
    # Validasi dusun
    valid_dusun = ['SATU', 'DUA', 'TIGA', 'EMPAT']
    if dusun not in valid_dusun:
        flash("Dusun tidak ditemukan.", "danger")
        return redirect(url_for('cetak_pilihan'))

    # Cek hak akses
    if current_user.role == 'kepala_dusun' and current_user.dusun != dusun:
        flash("Anda hanya bisa cetak KK di dusun Anda.", "danger")
        return redirect(url_for('cetak_pilihan'))
    elif current_user.role == 'masyarakat':
        flash("Anda tidak diizinkan mengakses fitur ini.", "danger")
        return redirect(url_for('index'))

    # Ambil semua KK di dusun tersebut
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT nik, nomor_kk, nama, hubungan, jenis_kelamin, tempat_lahir, 
               tanggal_lahir, agama, status_perkawinan, pendidikan, pekerjaan, 
               alamat, golongan_darah, dusun
        FROM penduduk 
        WHERE nomor_kk = ? AND nama IS NOT NULL AND TRIM(nama) != ''
        ORDER BY CASE WHEN hubungan='Kepala Keluarga' THEN 0 ELSE 1 END, nama                                                                                                               
    """, (dusun,))
    kk_rows = cursor.fetchall()
    conn.close()

    if not kk_rows:
        flash(f"Tidak ada data KK di Dusun {dusun}.", "info")
        return redirect(url_for('cetak_pilihan'))

    kks = [row['nomor_kk'] for row in kk_rows]

    # Buat PDF
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)

    for nomor_kk in kks:
        conn = get_db()
        rows = conn.execute("""
            SELECT * FROM penduduk 
            WHERE nomor_kk = ? 
            ORDER BY CASE WHEN hubungan='Kepala Keluarga' THEN 0 ELSE 1 END, nama
        """, (nomor_kk,)).fetchall()
        conn.close()

        if not rows:
            continue

        pdf.add_page()

        # Background watermark
        pdf.set_text_color(230, 230, 230)
        pdf.set_font("helvetica", 'B', 80)
        pdf.text(30, 100, "NAGORI BAHAPAL RAYA")
        pdf.set_text_color(0, 0, 0)

        # Logo
        try:
            pdf.image('static/img/logo_desa.png', x=10, y=10, w=20)
        except:
            pass

        # Header
        pdf.set_font("helvetica", 'B', 18)
        pdf.cell(0, 10, "KARTU KELUARGA", ln=True, align='C')
        pdf.set_font("helvetica", '', 14)
        pdf.cell(0, 8, f"No. KK: {nomor_kk}", ln=True, align='C')
        pdf.ln(10)

        # Garis pemisah
        pdf.set_draw_color(0, 0, 0)
        pdf.line(10, 40, 290, 40)
        pdf.ln(5)

        # Tabel
        pdf.set_font("helvetica", 'B', 9)
        col_widths = [28, 35, 18, 25, 25, 18, 20, 20, 25, 20, 20]
        headers = ["NIK", "Nama", "JK", "Tmpt Lahir", "Tgl Lahir", "Agama", "Status", "Pendidikan", "Pekerjaan", "Gol. Darah", "Hubungan"]
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 8, h, 1, 0, 'C')
        pdf.ln(8)

        pdf.set_font("helvetica", '', 8)
        for row in rows:
            # Hitung tinggi baris berdasarkan nama
            nama_lines = word_wrap(row['nama'], pdf, col_widths[1] - 1)
            height = max(8, len(nama_lines) * 4)  # Minimal 8mm

            x_before = pdf.get_x()
            y_before = pdf.get_y()

            # Kolom 1: NIK
            pdf.cell(col_widths[0], height, str(row['nik']), 1, 0, 'L')

            # Kolom 2: Nama (multi_cell)
            
            pdf.set_xy(x_before + col_widths[0], y_before)
            pdf.multi_cell(col_widths[1], 4, row['nama'], border=1, align='L')

            # Reset posisi Y
            pdf.set_xy(x_before + col_widths[0] + col_widths[1], y_before)

            # Kolom 3: JK
            pdf.cell(col_widths[2], height, row['jenis_kelamin'], 1, 0, 'C')
            # Kolom 4: Tempat Lahir
            pdf.cell(col_widths[3], height, row['tempat_lahir'], 1, 0, 'L')
            # Kolom 5: Tanggal Lahir
            pdf.cell(col_widths[4], height, row['tanggal_lahir'], 1, 0, 'L')
            # Kolom 6: Agama
            pdf.cell(col_widths[5], height, row['agama'], 1, 0, 'L')
            # Kolom 7: Status
            pdf.cell(col_widths[6], height, row['status_perkawinan'], 1, 0, 'L')
            # Kolom 8: Pendidikan
            pdf.cell(col_widths[7], height, row['pendidikan'], 1, 0, 'L')
            # Kolom 9: Pekerjaan
            pdf.cell(col_widths[8], height, row['pekerjaan'], 1, 0, 'L')
            # Kolom 10: Gol. Darah
            pdf.cell(col_widths[9], height, row['golongan_darah'], 1, 0, 'C')
            # Kolom 11: Hubungan
            pdf.cell(col_widths[10], height, row['hubungan'], 1, 0, 'L')

            # Pindah baris
            pdf.ln(height)

        # Footer
        pdf.ln(10)
        pdf.set_font("helvetica", 'I', 8)
        pdf.cell(0, 6, f"Dicetak oleh: {current_user.username} | Tanggal: {datetime.now().strftime('%d-%m-%Y %H:%M')}", 0, 1, 'C')

    os.makedirs("laporan/pdf", exist_ok=True)
    safe_dusun = sanitize_filename(dusun)
    filename = f"laporan/pdf/kk_dusun_{safe_dusun}.pdf"
    pdf.output(filename)
    return send_file(filename, as_attachment=True)

@app.route('/cetak/kk/dusun')
@login_required
def cetak_kk_per_dusun_form():
    dusun = request.args.get('dusun', '').strip()
    
    # Validasi dusun
    if not dusun:
        flash("Dusun tidak valid.", "danger")
        return redirect(url_for('cetak_pilihan'))
        
    valid_dusun = ['SATU', 'DUA', 'TIGA', 'EMPAT']
    if dusun not in valid_dusun:
        flash("Dusun tidak ditemukan.", "danger")
        return redirect(url_for('cetak_pilihan'))

    # Cek hak akses
    if current_user.role == 'kepala_dusun' and current_user.dusun != dusun:
        flash("Anda hanya bisa cetak KK di dusun Anda.", "danger")
        return redirect(url_for('cetak_pilihan'))
    elif current_user.role == 'masyarakat':
        flash("Anda tidak diizinkan mengakses fitur ini.", "danger")
        return redirect(url_for('index'))

    # Ambil semua KK di dusun tersebut
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT nomor_kk FROM penduduk 
        WHERE dusun = ? AND nomor_kk IS NOT NULL AND TRIM(nomor_kk) != ''
        ORDER BY nomor_kk
    """, (dusun,))
    kk_rows = cursor.fetchall()
    conn.close()

    if not kk_rows:
        flash(f"Tidak ada data KK di Dusun {dusun}.", "info")
        return redirect(url_for('cetak_pilihan'))

    kks = [row['nomor_kk'] for row in kk_rows]

    # Buat PDF
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)

    for nomor_kk in kks:
        conn = get_db()
        rows = conn.execute("""
            SELECT * FROM penduduk 
            WHERE nomor_kk = ? 
            ORDER BY CASE WHEN hubungan='Kepala Keluarga' THEN 0 ELSE 1 END, nama
        """, (nomor_kk,)).fetchall()
        conn.close()

        if not rows:
            continue

        pdf.add_page()

        # Background watermark
        pdf.set_text_color(230, 230, 230)
        pdf.set_font("helvetica", 'B', 80)
        pdf.text(30, 100, "NAGORI BAHAPAL RAYA")
        pdf.set_text_color(0, 0, 0)

        # Logo
        try:
            pdf.image('static/img/logo_desa.png', x=10, y=10, w=20)
        except:
            pass

        # Header
        pdf.set_font("helvetica", 'B', 18)
        pdf.cell(0, 10, "KARTU KELUARGA", ln=True, align='C')
        pdf.set_font("helvetica", '', 14)
        pdf.cell(0, 8, f"No. KK: {nomor_kk}", ln=True, align='C')
        pdf.ln(10)

        # Garis pemisah
        pdf.set_draw_color(0, 0, 0)
        pdf.line(10, 40, 290, 40)
        pdf.ln(5)

        # Tabel
        pdf.set_font("helvetica", 'B', 9)
        col_widths = [28, 35, 18, 25, 25, 18, 20, 20, 25, 20, 20]
        headers = ["NIK", "Nama", "JK", "Tmpt Lahir", "Tgl Lahir", "Agama", "Status", "Pendidikan", "Pekerjaan", "Gol. Darah", "Hubungan"]
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 8, h, 1, 0, 'C')
        pdf.ln(8)

        pdf.set_font("helvetica", '', 8)
        for row in rows:
            # Hitung tinggi baris berdasarkan nama
            nama_lines = word_wrap(row['nama'], pdf, col_widths[1] - 1)
            height = max(8, len(nama_lines) * 4)  # Minimal 8mm

            x_before = pdf.get_x()
            y_before = pdf.get_y()

            # Kolom 1: NIK
            pdf.cell(col_widths[0], height, str(row['nik']), 1, 0, 'L')

            # Kolom 2: Nama (multi_cell)
            pdf.set_xy(x_before + col_widths[0], y_before)
            pdf.multi_cell(col_widths[1], 4, row['nama'], border=1, align='L')

            # Reset posisi Y
            pdf.set_xy(x_before + col_widths[0] + col_widths[1], y_before)

            # Kolom 3: JK
            pdf.cell(col_widths[2], height, row['jenis_kelamin'], 1, 0, 'C')
            # Kolom 4: Tempat Lahir
            pdf.cell(col_widths[3], height, row['tempat_lahir'], 1, 0, 'L')
            # Kolom 5: Tanggal Lahir
            pdf.cell(col_widths[4], height, row['tanggal_lahir'], 1, 0, 'L')
            # Kolom 6: Agama
            pdf.cell(col_widths[5], height, row['agama'], 1, 0, 'L')
            # Kolom 7: Status
            pdf.cell(col_widths[6], height, row['status_perkawinan'], 1, 0, 'L')
            # Kolom 8: Pendidikan
            pdf.cell(col_widths[7], height, row['pendidikan'], 1, 0, 'L')
            # Kolom 9: Pekerjaan
            pdf.cell(col_widths[8], height, row['pekerjaan'], 1, 0, 'L')
            # Kolom 10: Gol. Darah
            pdf.cell(col_widths[9], height, row['golongan_darah'], 1, 0, 'C')
            # Kolom 11: Hubungan
            pdf.cell(col_widths[10], height, row['hubungan'], 1, 0, 'L')

            # Pindah baris
            pdf.ln(height)

        # Footer
        pdf.ln(10)
        pdf.set_font("helvetica", 'I', 8)
        pdf.cell(0, 6, f"Dicetak oleh: {current_user.username} | Tanggal: {datetime.now().strftime('%d-%m-%Y %H:%M')}", 0, 1, 'C')

    os.makedirs("laporan/pdf", exist_ok=True)
    safe_dusun = sanitize_filename(dusun)
    filename = f"laporan/pdf/kk_dusun_{safe_dusun}.pdf"
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
            if row['dusun'] in dusun_summary:
                dusun_summary[row['dusun']]['kk'] = row['kk']
            else:
                dusun_summary[row['dusun']] = {
                    'jiwa': 0, 'laki': 0, 'perempuan': 0, 'kk': row['kk']
                }
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
            # Cek username sudah ada
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM user WHERE username = ?", (username,))
            if cursor.fetchone()[0] > 0:
                flash("Username sudah ada.", "danger")
                return redirect(url_for('tambah_user'))
            
            # Tambah user baru
            conn.execute('''INSERT INTO user (username, password, role, dusun, nik_masyarakat)
                            VALUES (?, ?, ?, ?, ?)''', 
                        (username, password, role, dusun, nik_masyarakat))
            conn.commit()
            
            # ✅ Catat aktivitas
            catat_aktivitas(current_user.username, 'TAMBAH_USER', f"Tambah user: {username} ({role})")
            
            flash("User berhasil ditambahkan!", "success")
            load_users_from_db()
            
        except Exception as e:
            conn.rollback()
            flash(f"Gagal tambah user: {str(e)}", "danger")
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
    # ✅ Tambah: total_kk
    cursor.execute("SELECT COUNT(DISTINCT nomor_kk) FROM penduduk WHERE nomor_kk IS NOT NULL AND TRIM(nomor_kk) != ''")
    total_kk = cursor.fetchone()[0]

    conn.close()

    # Buat grafik
    create_charts(dusun_data, agama_data, pendidikan_data, pertumbuhan_data)

    # 🔴 Kirim total_jiwa ke template
    return render_template('dashboard.html',
                     dusun_data=dusun_data,
                     agama_data=agama_data,
                     pendidikan_data=pendidikan_data,
                     pertumbuhan_data=pertumbuhan_data,
                     total_jiwa=total_jiwa,
                     total_kk=total_kk)

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

    # 1. Target penduduk per dusun
    target_dusun = {
        'SATU': 150,
        'DUA': 120,
        'TIGA': 272,
        'EMPAT': 140
    }

    # 🔵 total_target = jumlah semua target dusun
    total_target = sum(target_dusun.values())  # 150+120+272+140 = 682

    # Ambil filter dari request (hanya untuk "Input per User")
    filter_dusun = request.args.get('dusun')
    tanggal = request.args.get('tanggal')

    start_date = None
    end_date = None
    if tanggal:
        try:
            parts = tanggal.split(' - ')
            start_date = parts[0].strip()
            end_date = parts[1].strip()
            datetime.strptime(start_date, '%Y-%m-%d')
            datetime.strptime(end_date, '%Y-%m-%d')
        except:
            flash("Format tanggal tidak valid. Gunakan format: YYYY-MM-DD", "warning")

    # ================================
    # 🔵 PROGRESS UTAMA (TANPA FILTER)
    # ================================
    cursor.execute("""
        SELECT dusun, COUNT(*) as jumlah 
        FROM penduduk 
        WHERE dusun IS NOT NULL AND TRIM(dusun) != ''
        GROUP BY dusun
    """)
    data_dusun = cursor.fetchall()

    progress_data = []
    total_terinput = 0  # Reset, akan diisi ulang
    for dusun, jumlah in data_dusun:
        target = target_dusun.get(dusun, 100)
        persen = min(100, round((jumlah / target) * 100))
        progress_data.append({
            'dusun': dusun,
            'terinput': jumlah,
            'target': target,
            'persen': persen
        })
        total_terinput += jumlah  # Akumulasi total terinput

    # 🔵 total_persen = (total_terinput / total_target) * 100
    total_persen = min(100, round((total_terinput / total_target) * 100)) if total_target > 0 else 0

    # =================================
    # 🟡 INPUT PER USER (DENGAN FILTER)
    # =================================
    query_user = """
        SELECT 
            u.username,
            u.username as nama,
            u.role,
            COUNT(p.nik) as jumlah_input
        FROM user u
        LEFT JOIN penduduk p ON (p.dusun = u.dusun OR p.nik = u.nik_masyarakat)
        WHERE 1=1
    """
    params_user = []

    if filter_dusun:
        query_user += " AND p.dusun = ?"
        params_user.append(filter_dusun)
    if start_date and end_date:
        query_user += " AND p.tanggal_input BETWEEN ? AND ?"
        params_user.extend([start_date, end_date])

    query_user += " GROUP BY u.id, u.username, u.role ORDER BY jumlah_input DESC"
    cursor.execute(query_user, params_user)
    data_per_user = cursor.fetchall()

    conn.close()

    # Hitung total input untuk persentase (hanya untuk tabel user)
    total_input = sum(row[3] for row in data_per_user) if data_per_user else 0

    return render_template(
        'progress.html',
        progress_data=progress_data,
        total_terinput=total_terinput,
        total_target=total_target,
        total_persen=total_persen,
        data_per_user=data_per_user,
        total_input=total_input,
        semua_dusun=target_dusun.keys(),
        filter_dusun=filter_dusun,
        tanggal_filter=tanggal,
        request=request
    )   
    # Di app.py, di akhir route /progress
    total_input = sum(row['jumlah_input'] for row in data_per_user) if data_per_user else 0

@app.route('/hapus/<nik>', methods=['GET', 'POST'])
@login_required
def hapus(nik):
    if request.method == 'POST':
        alasan = request.form.get('alasan', '').strip()
        if not alasan:
            flash("Pilih satu alasan penghapusan.", "danger")
            return redirect(url_for('index'))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT nik, nama, dusun, tempat_lahir, tanggal_lahir, 
                   jenis_kelamin, agama, status_perkawinan, pendidikan, 
                   pekerjaan, alamat, rt_rw, golongan_darah, hubungan, 
                   nomor_kk, kesejahteraan 
            FROM penduduk WHERE nik = ?
        """, (nik,))
        row = cursor.fetchone()

        if not row:
            flash("Data tidak ditemukan.", "warning")
            return redirect(url_for('index'))

        # Cek hak akses
        if current_user.role == 'kepala_dusun' and row['dusun'] != current_user.dusun:
            flash("Anda tidak diizinkan menghapus data di dusun ini.", "danger")
            return redirect(url_for('index'))
        elif current_user.role == 'masyarakat':
            flash("Anda tidak diizinkan menghapus data.", "danger")
            return redirect(url_for('index'))

        try:
            # Simpan SEMUA data ke log
            cursor.execute('''INSERT INTO log_penghapusan 
                (nik, nama, dusun, tempat_lahir, tanggal_lahir,
                 jenis_kelamin, agama, status_perkawinan, pendidikan,
                 pekerjaan, alamat, rt_rw, golongan_darah, hubungan,
                 nomor_kk, kesejahteraan, alasan_hapus, dihapus_oleh)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                tuple(row) + (alasan, current_user.username))
            
            # Hapus dari penduduk
            cursor.execute("DELETE FROM penduduk WHERE nik = ?", (nik,))
            conn.commit()
            flash(f"Data NIK {nik} berhasil dihapus!", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Gagal menghapus  {str(e)}", "danger")
        finally:
            conn.close()
        
        return redirect(url_for('index'))
    
    return redirect(url_for('index'))
 
@app.route('/riwayat_hapus', methods=['GET', 'POST'])
@login_required
def riwayat_hapus():
    if current_user.role != 'admin':
        flash("Akses ditolak.", "danger")
        return redirect(url_for('index'))
    
    conn = get_db()
    cursor = conn.cursor()
    
    if request.method == 'POST' and 'rollback_nik' in request.form:
        nik = request.form['rollback_nik'].strip()  # Tambah strip()
        
        # Validasi NIK
        if not nik or not re.match(r'^\d{16}$', nik):
            flash("NIK tidak valid.", "danger")
            conn.close()
            return redirect(url_for('riwayat_hapus'))
        
        # Ambil data dari log
        try:
            cursor.execute("""SELECT nik, nama, dusun, tempat_lahir, tanggal_lahir,
                                     jenis_kelamin, agama, status_perkawinan, pendidikan,
                                     pekerjaan, alamat, rt_rw, golongan_darah, hubungan,
                                     nomor_kk, kesejahteraan 
                              FROM log_penghapusan 
                              WHERE nik = ? ORDER BY tanggal_hapus DESC LIMIT 1""", (nik,))
            row = cursor.fetchone()
            
            if not row:
                flash(f"Data dengan NIK {nik} tidak ditemukan di log.", "warning")
            else:
                try:
                    # Cek apakah NIK sudah ada
                    cursor.execute("SELECT COUNT(*) FROM penduduk WHERE nik = ?", (nik,))
                    if cursor.fetchone()[0] > 0:
                        flash(f"NIK {nik} sudah ada di database. Tidak bisa dikembalikan.", "danger")
                    else:
                        # Kembalikan semua data
                        cursor.execute('''INSERT INTO penduduk 
                            (nik, nama, dusun, tempat_lahir, tanggal_lahir,
                             jenis_kelamin, agama, status_perkawinan, pendidikan,
                             pekerjaan, alamat, rt_rw, golongan_darah, hubungan,
                             nomor_kk, kesejahteraan, tanggal_input)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            tuple(row) + (datetime.now().strftime('%Y-%m-%d'),))
                        
                        # Hapus dari log setelah berhasil
                        cursor.execute("DELETE FROM log_penghapusan WHERE nik = ?", (nik,))
                        
                        conn.commit()
                        flash(f"Data NIK {nik} berhasil dikembalikan!", "success")
                
                except Exception as e:
                    conn.rollback()
                    flash(f"Gagal mengembalikan data: {str(e)}", "danger")
        
        except Exception as e:
            conn.rollback()
            flash(f"Error saat membaca log: {str(e)}", "danger")
    
    # Tampilkan semua riwayat
    try:
        cursor.execute("SELECT * FROM log_penghapusan ORDER BY tanggal_hapus DESC")
        riwayat = cursor.fetchall()
    except Exception as e:
        flash(f"Error baca riwayat: {str(e)}", "danger")
        riwayat = []
    
    conn.close()
    return render_template('riwayat_hapus.html', riwayat=riwayat)


@app.route('/log/aktivitas')
@login_required
def log_aktivitas():
    if current_user.role != 'admin':
        flash("Akses ditolak.", "danger")
        return redirect(url_for('index'))
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT username, aksi, detail, timestamp 
        FROM log_aktivitas 
        ORDER BY timestamp DESC 
        LIMIT 200
    """)
    logs = cursor.fetchall()
    conn.close()
    
    return render_template('log_aktivitas.html', logs=logs)

  
@app.route('/download/template/<filename>')
@login_required
def download_template(filename):
    try:
        return send_from_directory('template', filename, as_attachment=True)
    except FileNotFoundError:
        flash("Template tidak ditemukan.", "danger")
        return redirect(url_for('upload'))   
        
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