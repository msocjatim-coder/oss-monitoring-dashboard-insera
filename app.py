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
# AUTO REFRESH (SETIAP 10 DETIK)
# ============================================================
st_autorefresh(interval=10000, limit=None, key="autorefresh-10detik")

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
# FUNGSI MEMBACA DATA DARI SUPABASE (TANPA CACHE!)
# ============================================================
def load_data_from_supabase():
    """Membaca semua data dari tabel oss_data - selalu fresh"""
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
    
    # HAPUS KOLOM Unnamed
    unnamed_cols = [col for col in df.columns if 'Unnamed' in col or col == '']
    if unnamed_cols:
        df = df.drop(columns=unnamed_cols)
    
    # Bersihkan nama kolom
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
    
    # Buat kolom LAYANAN
    if "SUMMARY" in df.columns:
        df["LAYANAN"] = df["SUMMARY"].astype(str).apply(
            lambda x: "TSEL" if "TSEL" in x.upper() else "OLO"
        )
    else:
        df["LAYANAN"] = "UNKNOWN"
    
    # Hitung umur tiket
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

# Header
col1, col2 = st.columns([8, 2])

with col1:
    st.title("📊 OSS Monitoring Dashboard")

with col2:
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
                df_temp = pd.read_csv(uploaded_file, encoding="utf-8")
            except:
                df_temp = pd.read_csv(uploaded_file, encoding="latin1")
            
            all_dfs.append(df_temp)
        
        if all_dfs:
            df_upload = pd.concat(all_dfs, ignore_index=True)
            is_valid, msg = validate_csv(df_upload)
            
            if is_valid:
                df_upload = process_data(df_upload)
                
                if save_to_supabase(df_upload):
                    st.success(f"✅ Berhasil upload {len(df_upload)} tiket!")
                    st.balloons()
                    st.rerun()  # Refresh langsung setelah upload
                else:
                    st.error("❌ Gagal menyimpan ke Supabase")
            else:
                st.error(msg)

# ============================================================
# LOAD DATA DARI SUPABASE (FRESH SETIAP RENDER)
# ============================================================
with st.spinner("Memuat data..."):
    df_db = load_data_from_supabase()

# Jika tidak ada data
if df_db.empty:
    st.warning("⚠️ Belum ada data. Silakan upload CSV terlebih dahulu.")
    st.info("📤 Klik tombol 'Browse files' di pojok kanan atas untuk upload")
    st.stop()

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
# KOLOM YANG AKAN DITAMPILKAN DI TABEL TIKET OPEN DAN CLOSE
# ============================================================
kolom_tampil = ["INCIDENT", "STATUS", "WITEL", "REPORTED DATE", "SUMMARY", "LAYANAN", "UMUR_TIKET_HARI"]
kolom_tampil = [k for k in kolom_tampil if k in df_display.columns]

# ============================================================
# MEMBUAT 3 TAB MENU
# ============================================================
tab1, tab2, tab3 = st.tabs(["📂 TIKET OPEN", "📁 TIKET CLOSE", "📥 DOWNLOAD TIKET"])

with tab1:
    st.subheader("🔍 Tiket Open (Status Aktif)")
    
    # FILTER UNTUK TAB OPEN
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        if "WITEL" in df_display.columns:
            semua_witel = sorted(df_display["WITEL"].dropna().unique())
            pilih_witel_open = st.multiselect("Pilih WITEL", semua_witel, default=[], key="witel_open")
        else:
            pilih_witel_open = []
    
    with col_f2:
        if "LAYANAN" in df_display.columns:
            semua_layanan = sorted(df_display["LAYANAN"].unique())
            pilih_layanan_open = st.multiselect("Pilih LAYANAN", semua_layanan, default=[], key="layanan_open")
        else:
            pilih_layanan_open = []
    
    with col_f3:
        cari_incident_open = st.text_input("🔎 Cari INCIDENT", placeholder="Ketik nomor INC...", key="cari_open")
    
    # Filter data untuk tiket OPEN
    df_open = df_display[df_display["IS_ACTIVE"] == True].copy() if "IS_ACTIVE" in df_display.columns else df_display.copy()
    
    if pilih_witel_open and "WITEL" in df_open.columns:
        df_open = df_open[df_open["WITEL"].isin(pilih_witel_open)]
    if pilih_layanan_open and "LAYANAN" in df_open.columns:
        df_open = df_open[df_open["LAYANAN"].isin(pilih_layanan_open)]
    if cari_incident_open and "INCIDENT" in df_open.columns:
        df_open = df_open[df_open["INCIDENT"].astype(str).str.contains(cari_incident_open, case=False, na=False)]
    
    # Tampilkan tabel tiket OPEN
    if df_open.empty:
        st.info("Tidak ada tiket open")
    else:
        st.dataframe(
            df_open[kolom_tampil],
            use_container_width=True,
            hide_index=True
        )
        st.caption(f"Menampilkan {len(df_open)} tiket open")

with tab2:
    st.subheader("🔍 Tiket Close (Status Tidak Aktif)")
    
    # FILTER UNTUK TAB CLOSE
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        if "WITEL" in df_display.columns:
            semua_witel = sorted(df_display["WITEL"].dropna().unique())
            pilih_witel_close = st.multiselect("Pilih WITEL", semua_witel, default=[], key="witel_close")
        else:
            pilih_witel_close = []
    
    with col_f2:
        if "LAYANAN" in df_display.columns:
            semua_layanan = sorted(df_display["LAYANAN"].unique())
            pilih_layanan_close = st.multiselect("Pilih LAYANAN", semua_layanan, default=[], key="layanan_close")
        else:
            pilih_layanan_close = []
    
    with col_f3:
        cari_incident_close = st.text_input("🔎 Cari INCIDENT", placeholder="Ketik nomor INC...", key="cari_close")
    
    # Filter data untuk tiket CLOSE
    df_close = df_display[df_display["IS_ACTIVE"] == False].copy() if "IS_ACTIVE" in df_display.columns else pd.DataFrame()
    
    if not df_close.empty:
        if pilih_witel_close and "WITEL" in df_close.columns:
            df_close = df_close[df_close["WITEL"].isin(pilih_witel_close)]
        if pilih_layanan_close and "LAYANAN" in df_close.columns:
            df_close = df_close[df_close["LAYANAN"].isin(pilih_layanan_close)]
        if cari_incident_close and "INCIDENT" in df_close.columns:
            df_close = df_close[df_close["INCIDENT"].astype(str).str.contains(cari_incident_close, case=False, na=False)]
    
    # Tampilkan tabel tiket CLOSE
    if df_close.empty:
        st.info("Tidak ada tiket close")
    else:
        st.dataframe(
            df_close[kolom_tampil],
            use_container_width=True,
            hide_index=True
        )
        st.caption(f"Menampilkan {len(df_close)} tiket close")

with tab3:
    st.subheader("📥 Download Tiket (Semua Kolom)")
    
    # FILTER UNTUK TAB DOWNLOAD
    col_d1, col_d2, col_d3, col_d4 = st.columns(4)
    
    with col_d1:
        # Filter Tanggal Mulai
        if "REPORTED DATE" in df_display.columns:
            # Konversi ke datetime untuk mengambil min/max
            df_temp = df_display.copy()
            df_temp["REPORTED DATE"] = pd.to_datetime(df_temp["REPORTED DATE"])
            min_date = df_temp["REPORTED DATE"].min().date()
            max_date = df_temp["REPORTED DATE"].max().date()
            tgl_mulai = st.date_input("Dari Tanggal", min_date, key="tgl_mulai")
        else:
            tgl_mulai = None
    
    with col_d2:
        # Filter Tanggal Akhir
        if "REPORTED DATE" in df_display.columns:
            tgl_akhir = st.date_input("Sampai Tanggal", max_date, key="tgl_akhir")
        else:
            tgl_akhir = None
    
    with col_d3:
        # Filter WITEL
        if "WITEL" in df_display.columns:
            semua_witel = sorted(df_display["WITEL"].dropna().unique())
            pilih_witel_download = st.multiselect("Pilih WITEL", semua_witel, default=[], key="witel_download")
        else:
            pilih_witel_download = []
    
    with col_d4:
        # Filter LAYANAN
        if "LAYANAN" in df_display.columns:
            semua_layanan = sorted(df_display["LAYANAN"].unique())
            pilih_layanan_download = st.multiselect("Pilih LAYANAN", semua_layanan, default=[], key="layanan_download")
        else:
            pilih_layanan_download = []
    
    # Filter data untuk download - gunakan data asli dari database (semua kolom)
    df_download = df_db.copy()
    
    # Terapkan filter tanggal
    if "REPORTED DATE" in df_download.columns and tgl_mulai and tgl_akhir:
        df_download["REPORTED DATE"] = pd.to_datetime(df_download["REPORTED DATE"])
        mask_tanggal = (df_download["REPORTED DATE"].dt.date >= tgl_mulai) & (df_download["REPORTED DATE"].dt.date <= tgl_akhir)
        df_download = df_download[mask_tanggal]
    
    # Terapkan filter WITEL
    if pilih_witel_download and "WITEL" in df_download.columns:
        df_download = df_download[df_download["WITEL"].isin(pilih_witel_download)]
    
    # Terapkan filter LAYANAN
    if pilih_layanan_download and "LAYANAN" in df_download.columns:
        df_download = df_download[df_download["LAYANAN"].isin(pilih_layanan_download)]
    
    # Tampilkan jumlah data
    st.caption(f"Menampilkan {len(df_download)} tiket")
    
    # Tampilkan dataframe dengan semua kolom
    if df_download.empty:
        st.info("Tidak ada data dengan filter yang dipilih")
    else:
        st.dataframe(
            df_download,
            use_container_width=True,
            hide_index=True
        )
        
        # Tombol download dengan semua kolom
        csv_data = df_download.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Data Terfilter (Semua Kolom)",
            data=csv_data,
            file_name=f"oss_download_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True
        )

# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
wib_time = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%H:%M")
st.caption(f"🔄 Auto-refresh setiap 10 detik | Data terakhir diperbarui pukul {wib_time} WIB")
