import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import time
from streamlit_autorefresh import st_autorefresh

# Supabase
from supabase import create_client

# ============================================================
# KONFIGURASI HALAMAN
# ============================================================
st.set_page_config(
    page_title="OSS Monitoring Dashboard",
    page_icon="📊",
    layout="wide"
)

# ============================================================
# AUTO REFRESH (setiap 5 menit)
# ============================================================
st_autorefresh(interval=300000, limit=None, key="datarefresh")

# ============================================================
# KONEKSI KE SUPABASE
# ============================================================
@st.cache_resource
def init_supabase():
    """Inisialisasi koneksi Supabase"""
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["anon_key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Gagal konek ke Supabase: {str(e)}")
        return None

# ============================================================
# FUNGSI MEMBACA DATA DARI SUPABASE (TANPA CACHE)
# ============================================================
def load_data_from_supabase():
    """Membaca semua data dari tabel oss_data"""
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    
    try:
        response = supabase.table('oss_data').select('*').execute()
        df = pd.DataFrame(response.data)
        
        # Hapus kolom internal
        if 'id' in df.columns:
            df = df.drop(columns=['id'])
        if 'created_at' in df.columns:
            df = df.drop(columns=['created_at'])
            
        return df
        
    except Exception as e:
        st.error(f"Gagal baca data: {str(e)}")
        return pd.DataFrame()

# ============================================================
# FUNGSI MENYIMPAN DATA KE SUPABASE
# ============================================================
def save_to_supabase(df):
    """Menyimpan DataFrame ke Supabase"""
    supabase = init_supabase()
    if supabase is None:
        return False
    
    try:
        # Konversi dataframe ke records
        records = df.to_dict('records')
        
        # Bersihkan nilai yang tidak bisa di-JSON
        for record in records:
            for key, value in list(record.items()):
                if pd.isna(value):
                    record[key] = None
                elif isinstance(value, pd.Timestamp):
                    record[key] = value.isoformat() if pd.notna(value) else None
        
        # Upsert ke database berdasarkan INCIDENT
        supabase.table('oss_data').upsert(records, on_conflict='INCIDENT').execute()
        return True
        
    except Exception as e:
        st.error(f"Gagal simpan data: {str(e)}")
        return False

# ============================================================
# FUNGSI VALIDASI CSV
# ============================================================
def validate_csv(df):
    """Memeriksa apakah CSV memiliki kolom yang diperlukan"""
    required_columns = ["INCIDENT", "STATUS", "WITEL", "REPORTED DATE", "SUMMARY"]
    missing = [col for col in required_columns if col not in df.columns]
    
    if missing:
        return False, f"Kolom berikut tidak ditemukan: {missing}"
    
    return True, "OK"

# ============================================================
# FUNGSI MEMPROSES DATA
# ============================================================
def process_data(df):
    """Membersihkan data dan menambah kolom analisis"""
    df = df.copy()
    
    # HAPUS KOLOM Unnamed (kolom indeks dari CSV)
    unnamed_cols = [col for col in df.columns if 'Unnamed' in col or col == '']
    if unnamed_cols:
        df = df.drop(columns=unnamed_cols)
    
    # Bersihkan nama kolom dari karakter aneh
    df.columns = (
        df.columns
        .str.strip()
        .str.replace('"', '', regex=False)
    )
    
    # CEK DUPLIKAT INCIDENT
    if "INCIDENT" in df.columns:
        df = df.drop_duplicates(subset=["INCIDENT"], keep="first")
    
    # Konversi kolom datetime
    date_columns = ["REPORTED DATE", "STATUS DATE", "DATEMODIFIED", "LAST UPDATE WORKLOG", "RESOLVE DATE"]
    for col in date_columns:
        if col in df.columns:
            try:
                df[col] = pd.to_datetime(df[col], errors="coerce")
            except:
                df[col] = pd.NaT
    
    # Buat kolom LAYANAN untuk analisis
    if "SUMMARY" in df.columns:
        df["LAYANAN"] = df["SUMMARY"].astype(str).apply(
            lambda x: "TSEL" if "TSEL" in x.upper() else "OLO"
        )
    else:
        df["LAYANAN"] = "UNKNOWN"
    
    # Hitung umur tiket (hari) untuk analisis
    if "REPORTED DATE" in df.columns:
        now = datetime.now()
        df["UMUR_TIKET_HARI"] = (now - df["REPORTED DATE"]).dt.days
        df["UMUR_TIKET_HARI"] = df["UMUR_TIKET_HARI"].fillna(0).astype(int)
    else:
        df["UMUR_TIKET_HARI"] = 0
    
    # Tentukan status aktif
    if "STATUS" in df.columns:
        df["IS_ACTIVE"] = ~df["STATUS"].astype(str).str.lower().isin(
            ["closed", "resolved", "cancel"]
        )
    else:
        df["IS_ACTIVE"] = True
    
    return df

# ============================================================
# TAMPILAN UTAMA DASHBOARD
# ============================================================

# Header dengan tombol refresh
col1, col2, col3 = st.columns([8, 1, 2])

with col1:
    st.title("📊 OSS Monitoring Dashboard")
    st.caption("Data tersimpan otomatis di Supabase")

with col2:
    if st.button("🔄 Refresh"):
        st.rerun()

with col3:
    uploaded_files = st.file_uploader(
        "Upload CSV",
        type=["csv"],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )

# ============================================================
# HANDLE UPLOAD FILE
# ============================================================
if uploaded_files:
    with st.spinner("Memproses file..."):
        all_dfs = []
        
        for uploaded_file in uploaded_files:
            try:
                # Coba baca dengan utf-8 dulu
                df_temp = pd.read_csv(uploaded_file, encoding="utf-8")
            except:
                # Fallback ke latin1
                df_temp = pd.read_csv(uploaded_file, encoding="latin1")
            
            all_dfs.append(df_temp)
        
        # Gabungkan semua file
        if all_dfs:
            df_upload = pd.concat(all_dfs, ignore_index=True)
            
            # Validasi
            is_valid, msg = validate_csv(df_upload)
            
            if is_valid:
                # Proses data
                df_upload = process_data(df_upload)
                
                # Simpan ke Supabase
                if save_to_supabase(df_upload):
                    st.success(f"✅ Berhasil upload {len(df_upload)} tiket!")
                    st.balloons()
                    st.rerun()
                else:
                    st.error("❌ Gagal menyimpan ke Supabase")
            else:
                st.error(msg)

# ============================================================
# LOAD DATA DARI SUPABASE
# ============================================================
df_db = pd.DataFrame()  # Inisialisasi kosong

with st.spinner("Memuat data..."):
    try:
        df_db = load_data_from_supabase()
    except Exception as e:
        st.error(f"Error: {str(e)}")

# Jika tidak ada data
if df_db.empty:
    st.warning("⚠️ Belum ada data. Silakan upload CSV terlebih dahulu.")
    st.info("📤 Klik tombol 'Browse files' di pojok kanan atas untuk upload")
    st.stop()  # Hentikan eksekusi di sini

# Kalau ada data, lanjutkan
st.success(f"✅ Menampilkan {len(df_db)} tiket")

# ============================================================
# SIAPKAN DATA UNTUK DITAMPILKAN
# ============================================================
df_display = df_db.copy()

# ============================================================
# METRIKS RINGKASAN
# ============================================================
st.markdown("---")

col1, col2, col3, col4 = st.columns(4)

with col1:
    total_tiket = len(df_display)
    aktif = len(df_display[df_display["IS_ACTIVE"] == True]) if "IS_ACTIVE" in df_display.columns else 0
    st.metric("📋 TOTAL TIKET", f"{total_tiket}", f"{aktif} aktif")

with col2:
    if "LAYANAN" in df_display.columns:
        tsel = len(df_display[df_display["LAYANAN"] == "TSEL"])
        olo = len(df_display[df_display["LAYANAN"] == "OLO"])
        st.metric("📊 LAYANAN", f"{tsel} TSEL", f"{olo} OLO")
    else:
        st.metric("📊 LAYANAN", "N/A")

with col3:
    if "UMUR_TIKET_HARI" in df_display.columns:
        umur_rata = df_display["UMUR_TIKET_HARI"].mean()
        st.metric("⏳ RATA-RATA UMUR", f"{umur_rata:.1f} hari")
    else:
        st.metric("⏳ RATA-RATA UMUR", "N/A")

with col4:
    if "STATUS" in df_display.columns:
        status_counts = df_display["STATUS"].value_counts()
        top_status = status_counts.index[0] if not status_counts.empty else "-"
        st.metric("⚡ STATUS TERBANYAK", top_status, f"{status_counts.iloc[0]} tiket")
    else:
        st.metric("⚡ STATUS TERBANYAK", "-")

st.markdown("---")

# ============================================================
# FILTER
# ============================================================
with st.expander("🔍 Filter Data", expanded=True):
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if "WITEL" in df_display.columns:
            semua_witel = sorted(df_display["WITEL"].dropna().unique())
            pilih_witel = st.multiselect("Pilih WITEL", semua_witel, default=[])
        else:
            pilih_witel = []
    
    with col2:
        if "STATUS" in df_display.columns:
            semua_status = sorted(df_display["STATUS"].dropna().unique())
            pilih_status = st.multiselect("Pilih STATUS", semua_status, default=[])
        else:
            pilih_status = []
    
    with col3:
        if "LAYANAN" in df_display.columns:
            semua_layanan = sorted(df_display["LAYANAN"].unique())
            pilih_layanan = st.multiselect("Pilih LAYANAN", semua_layanan, default=[])
        else:
            pilih_layanan = []
    
    cari_incident = st.text_input("🔎 Cari INCIDENT", placeholder="Ketik nomor INC...")

# Terapkan filter
df_filtered = df_display.copy()

if pilih_witel and "WITEL" in df_filtered.columns:
    df_filtered = df_filtered[df_filtered["WITEL"].isin(pilih_witel)]
if pilih_status and "STATUS" in df_filtered.columns:
    df_filtered = df_filtered[df_filtered["STATUS"].isin(pilih_status)]
if pilih_layanan and "LAYANAN" in df_filtered.columns:
    df_filtered = df_filtered[df_filtered["LAYANAN"].isin(pilih_layanan)]
if cari_incident and "INCIDENT" in df_filtered.columns:
    df_filtered = df_filtered[df_filtered["INCIDENT"].astype(str).str.contains(cari_incident, case=False, na=False)]

# ============================================================
# TABEL DATA
# ============================================================
st.subheader(f"📋 Data Tiket ({len(df_filtered)} dari {len(df_display)})")

# Kolom yang ditampilkan
kolom_tampil = ["INCIDENT", "STATUS", "WITEL", "REPORTED DATE", "SUMMARY", "LAYANAN", "UMUR_TIKET_HARI"]
kolom_tampil = [k for k in kolom_tampil if k in df_filtered.columns]

st.dataframe(
    df_filtered[kolom_tampil],
    use_container_width=True,
    hide_index=True
)

# ============================================================
# STATISTIK
# ============================================================
with st.expander("📈 Statistik Lengkap", expanded=False):
    
    if "WITEL" in df_filtered.columns:
        st.subheader("Tiket per WITEL")
        witel_stats = df_filtered["WITEL"].value_counts().reset_index()
        witel_stats.columns = ["WITEL", "JUMLAH"]
        st.dataframe(witel_stats, use_container_width=True, hide_index=True)
    
    if "STATUS" in df_filtered.columns:
        st.subheader("Tiket per STATUS")
        status_stats = df_filtered["STATUS"].value_counts().reset_index()
        status_stats.columns = ["STATUS", "JUMLAH"]
        st.dataframe(status_stats, use_container_width=True, hide_index=True)

# ============================================================
# DOWNLOAD DATA
# ============================================================
st.markdown("---")
col1, col2 = st.columns(2)

with col1:
    csv_all = df_display.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Semua Data",
        data=csv_all,
        file_name=f"oss_data_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        use_container_width=True
    )

with col2:
    if "IS_ACTIVE" in df_display.columns:
        df_aktif = df_display[df_display["IS_ACTIVE"] == True].copy()
        csv_active = df_aktif.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Data Aktif",
            data=csv_active,
            file_name=f"oss_active_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True
        )

# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
st.caption(f"🔄 Update terakhir: {datetime.now().strftime('%H:%M:%S')}")
