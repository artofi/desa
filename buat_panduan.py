# buat_panduan.py
from fpdf import FPDF
import os

# Cek dan instal fpdf jika belum
try:
    from fpdf import FPDF
except ImportError:
    print("Sedang menginstal fpdf...")
    os.system("pip install fpdf")
    from fpdf import FPDF

# Gunakan font standar: Helvetica (tanpa karakter Unicode)
pdf = FPDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()
pdf.set_font("helvetica", "B", 16)
pdf.cell(0, 10, "PANDUAN APLIKASI KELOLA DATA PENDUDUK", align="C", new_x="LMARGIN", new_y="NEXT")
pdf.set_font("helvetica", "", 12)
pdf.cell(0, 10, "Desa Nagori Bahapal Raya", align="C", new_x="LMARGIN", new_y="NEXT")
pdf.ln(10)

# Data Panduan (tanpa karakter seperti ├, └, │)
halaman = [
    "1. INSTALASI PYTHON\n\n"
    "Download Python 3.11+ dari https://www.python.org/downloads/\n"
    "Centang 'Add Python to PATH' saat instalasi.\n\n"
    "Cek versi:\n"
    "  Buka CMD, ketik:\n"
    "  python --version\n"
    "  pip --version",

    "2. INSTAL LIBRARY\n\n"
    "Buka CMD di folder aplikasi, jalankan:\n"
    "pip install flask flask-login sqlite3 pandas fpdf matplotlib openpyxl",

    "3. STRUKTUR FOLDER\n\n"
    "Letakkan aplikasi di folder pendek:\n"
    "C:\\desa\\\n\n"
    "Isi folder:\n"
    "  app.py\n"
    "  desa.db\n"
    "  templates\\ (file HTML)\n"
    "  static\\ (CSS, gambar)\n"
    "  laporan\\ (cetak PDF)\n"
    "  ekspor\\ (file Excel)\n"
    "  backup\\ (backup otomatis)",

    "4. JALANKAN APLIKASI\n\n"
    "Buka CMD, masuk ke folder:\n"
    "cd C:\\desa\n\n"
    "Jalankan:\n"
    "python app.py\n\n"
    "Buka di browser:\n"
    "http://127.0.0.1:5000",

    "5. LOGIN & HAK AKSES\n\n"
    "Admin: admin / 1234\n"
    "Kepala Dusun: kepala_satu / 1234\n"
    "Masyarakat: warga1 / 1234",

    "6. TAMBAH DATA\n\n"
    "- NIK & KK: 16 digit angka\n"
    "- Nama: otomatis kapital (huruf besar)\n"
    "- Dusun: pilih satu\n"
    "- Tidak boleh angka di nama",

    "7. UPLOAD EXCEL\n\n"
    "- Format: .xlsx\n"
    "- Kolom wajib: NIK, KK, Nama, Hubungan, Dusun\n"
    "- Hanya admin & kepala dusun yang bisa upload",

    "8. CETAK LAPORAN\n\n"
    "- Cetak KK per nomor\n"
    "- Cetak per NIK\n"
    "- Cetak statistik (PDF)",

    "9. AKSES DARI HP LAIN\n\n"
    "- Satu jaringan WiFi\n"
    "- Cek IP HP server (di WiFi)\n"
    "- Buka: http://[IP_Hp_Server]:5000",

    "10. SOLUSI MAX_PATH (260 Karakter)\n\n"
    "Error: Path too long\n\n"
    "Solusi:\n"
    "1. Aktifkan Long Path:\n"
    "   Buka PowerShell (Admin)\n"
    "   Jalankan:\n"
    "   New-ItemProperty -Path \"HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem\" -Name \"LongPathsEnabled\" -Value 1 -PropertyType DWORD -Force\n"
    "   Restart komputer.\n\n"
    "2. Pindah folder ke:\n"
    "   C:\\desa\\\n"
    "   (Jangan simpan di folder panjang)"
]

# Tambahkan ke PDF
for i, content in enumerate(halaman):
    pdf.set_font("helvetica", "B", 14)
    pdf.cell(0, 10, f"Halaman {i+1}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 11)
    pdf.multi_cell(0, 6, content)
    pdf.add_page()

# Simpan PDF
pdf.output("Panduan_Aplikasi_Desa_Nagori_Bahapal_Raya.pdf")
print("✅ Panduan berhasil dibuat! File: Panduan_Aplikasi_Desa_Nagori_Bahapal_Raya.pdf")