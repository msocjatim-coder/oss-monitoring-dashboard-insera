import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import os
from streamlit_autorefresh import st_autorefresh

# GOOGLE SHEET
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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
# KONEKSI KE GOOGLE SHEET
# ============================================================
@st.cache_resource
def connect_google_sheet():
    """
    Menghubungkan ke Google Sheet menggunakan credentials dari secrets
    """
    try:
        # Ambil credentials dari secrets
        credentials_info = {
            "type": st.secrets["gcp_service_account"]["type"],
            "project_id": st.secrets["gcp_service_account"]["project_id"],
            "private_key_id": st.secrets["gcp_service_account"]["private_key_id"],
            "private_key": st.secrets["gcp_service_account"]["private_key"],
            "client_email": st.secrets["gcp_service_account"]["client_email"],
            "client_id": st.secrets["gcp_service_account"]["client_id"],
            "token_uri": st.secrets["gcp_service_account"]["token_uri"],
        }
        
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_info, scope)
        client = gspread.authorize(creds)
        
        # Buka sheet
        sheet = client.open("OSS Incident Insera").sheet1
        return sheet
        
    except Exception as e:
        st.error(f"Gagal konek ke Google Sheet: {str(e)}")
        return None

# ============================================================
# FUNGSI MEMBACA DATA DARI GOOGLE SHEET
# ============================================================
@st.cache_data(ttl=300)  # Cache 5 menit
def load_data_from_sheet():
    """
    Membaca semua data dari Google Sheet dan mengubahnya ke DataFrame
    """
    sheet = connect_google_sheet()
    if sheet is None:
        return pd.DataFrame()
    
    try:
        # Ambil semua data
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        # Jika kosong, buat dataframe dengan kolom yang benar
        if df.empty:
            df = pd.DataFrame(columns=["INCIDENT", "STATUS", "WITEL", "REPORTED DATE", "SUMMARY"])
        
        return df
        
    except Exception as e:
        st.error(f"Gagal baca data: {str(e)}")
        return pd.DataFrame()

# ============================================================
# FUNGSI MENYIMPAN DATA KE GOOGLE SHEET
# ============================================================
def save_to_sheet(df):
    """
    Menyimpan DataFrame ke Google Sheet (menimpa data lama)
    """
    sheet = connect_google_sheet()
    if sheet is None:
        return False
    
    try:
        # Bersihkan sheet
        sheet.clear()
        
        # Buat salinan dataframe untuk diproses
        df_to_save = df.copy()
        
        # Konversi semua kolom datetime ke string
        for col in df_to_save.columns:
            if pd.api.types.is_datetime64_any_dtype(df_to_save[col]):
                df_to_save[col] = df_to_save[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Konversi semua kolom ke string untuk keamanan
        df_to_save = df_to_save.astype(str)
        
        # Siapkan data untuk diupdate
        headers = df_to_save.columns.tolist()
        values = df_to_save.values.tolist()
        
        # Gabungkan header dan values
        all_data = [headers] + values
        
        # Update ke sheet
        sheet.update(all_data)
        
        return True
        
    except Exception as e:
        st.error(f"Gagal simpan data: {str(e)}")
        return False

# ============================================================
# FUNGSI VALIDASI CSV
# ============================================================
def validate_csv(df):
    """
    Memeriksa apakah CSV memiliki kolom yang diperlukan
    """
    required_columns = ["INCIDENT", "STATUS", "WITEL", "REPORTED DATE", "SUMMARY"]
    missing = [col for col in required_columns if col not in df.columns]
    
    if missing:
        return False, f"Kolom berikut tidak ditemukan: {missing}"
    
    return True, "OK"

# ============================================================
# FUNGSI MEMPROSES DATA
# ============================================================
def process_data(df):
    """
    Menambahkan kolom-kolom analisis ke dataframe
    """
    df = df.copy()
    
    # Buat kolom LAYANAN (TSEL atau OLO)
    df["LAYANAN"] = df["SUMMARY"].astype(str).apply(
        lambda x: "TSEL" if "TSEL" in x.upper() else "OLO"
    )
    
    # Konversi REPORTED DATE ke datetime
    try:
        df["REPORTED DATE"] = pd.to_datetime(df["REPORTED DATE"], errors="coerce")
    except:
        df["REPORTED DATE"] = pd.NaT
    
    # Hitung umur tiket (hari)
    now = datetime.now()
    df["UMUR_TIKET_HARI"] = (now - df["REPORTED DATE"]).dt.days
    
    # Tentukan status aktif (belum closed/resolved/cancel)
    df["IS_ACTIVE"] = ~df["STATUS"].astype(str).str.lower().isin(
        ["closed", "resolved", "cancel"]
    )
    
    return df

# ============================================================
# TAMPILAN UTAMA DASHBOARD
# ============================================================

# Header dan Upload
col1, col2 = st.columns([8, 2])

with col1:
    st.title("📊 OSS Monitoring Dashboard")
    st.caption("Data tersimpan otomatis di Google Sheet")

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
                # Coba baca dengan utf-8 dulu
                df_temp = pd.read_csv(uploaded_file, encoding="utf-8")
            except:
                # Fallback ke latin1
                df_temp = pd.read_csv(uploaded_file, encoding="latin1")
            
            # Bersihkan nama kolom
            df_temp.columns = (
                df_temp.columns
                .str.strip()
                .str.replace('"', '', regex=False)
            )
            
            all_dfs.append(df_temp)
        
        # Gabungkan semua file
        if all_dfs:
            df_upload = pd.concat(all_dfs, ignore_index=True)
            
            # Validasi
            is_valid, msg = validate_csv(df_upload)
            
            if is_valid:
                # Proses data
                df_upload = process_data(df_upload)
                
                # Simpan ke Google Sheet
                if save_to_sheet(df_upload):
                    st.success(f"✅ Berhasil upload {len(df_upload)} tiket!")
                    st.balloons()
                    st.rerun()  # Refresh halaman
                else:
                    st.error("❌ Gagal menyimpan ke Google Sheet")
            else:
                st.error(msg)

# ============================================================
# LOAD DATA DARI GOOGLE SHEET
# ============================================================
with st.spinner("Memuat data..."):
    df = load_data_from_sheet()

# Jika tidak ada data
if df.empty:
    st.warning("Belum ada data. Silakan upload CSV terlebih dahulu.")
    st.stop()

# Proses data
df = process_data(df)

# ============================================================
# METRIKS RINGKASAN
# ============================================================
st.markdown("---")

col1, col2, col3, col4 = st.columns(4)

with col1:
    total_tiket = len(df)
    aktif = len(df[df["IS_ACTIVE"] == True])
    st.metric(
        label="📋 TOTAL TIKET",
        value=f"{total_tiket}",
        delta=f"{aktif} aktif"
    )

with col2:
    tsel = len(df[df["LAYANAN"] == "TSEL"])
    olo = len(df[df["LAYANAN"] == "OLO"])
    st.metric(
        label="📊 BERDASARKAN LAYANAN",
        value=f"{tsel} TSEL",
        delta=f"{olo} OLO"
    )

with col3:
    umur_rata = df["UMUR_TIKET_HARI"].mean()
    if pd.notna(umur_rata):
        st.metric(
            label="⏳ UMUR RATA-RATA",
            value=f"{umur_rata:.1f} hari"
        )
    else:
        st.metric(label="⏳ UMUR RATA-RATA", value="N/A")

with col4:
    status_counts = df["STATUS"].value_counts()
    top_status = status_counts.index[0] if not status_counts.empty else "-"
    st.metric(
        label="⚡ STATUS TERBANYAK",
        value=f"{top_status}",
        delta=f"{status_counts.iloc[0] if not status_counts.empty else 0} tiket"
    )

st.markdown("---")

# ============================================================
# FILTER
# ============================================================
with st.expander("🔍 Filter Data", expanded=True):
    col1, col2, col3 = st.columns(3)
    
    with col1:
        semua_witel = sorted(df["WITEL"].dropna().unique())
        pilih_witel = st.multiselect("Pilih WITEL", semua_witel, default=[])
    
    with col2:
        semua_status = sorted(df["STATUS"].dropna().unique())
        pilih_status = st.multiselect("Pilih STATUS", semua_status, default=[])
    
    with col3:
        semua_layanan = sorted(df["LAYANAN"].unique())
        pilih_layanan = st.multiselect("Pilih LAYANAN", semua_layanan, default=[])
    
    cari_incident = st.text_input("🔎 Cari INCIDENT", placeholder="Ketik nomor INC...")

# Terapkan filter
df_filtered = df.copy()

if pilih_witel:
    df_filtered = df_filtered[df_filtered["WITEL"].isin(pilih_witel)]
if pilih_status:
    df_filtered = df_filtered[df_filtered["STATUS"].isin(pilih_status)]
if pilih_layanan:
    df_filtered = df_filtered[df_filtered["LAYANAN"].isin(pilih_layanan)]
if cari_incident:
    df_filtered = df_filtered[df_filtered["INCIDENT"].astype(str).str.contains(cari_incident, case=False, na=False)]

# ============================================================
# TABEL DATA
# ============================================================
st.subheader(f"📋 Data Tiket ({len(df_filtered)} dari {len(df)})")

# Kolom yang ditampilkan
kolom_tampil = ["INCIDENT", "STATUS", "WITEL", "REPORTED DATE", "SUMMARY", "LAYANAN", "UMUR_TIKET_HARI"]

# Hanya tampilkan kolom yang ada
kolom_tampil = [k for k in kolom_tampil if k in df_filtered.columns]

# Tampilkan dataframe
st.dataframe(
    df_filtered[kolom_tampil],
    use_container_width=True,
    hide_index=True,
    column_config={
        "UMUR_TIKET_HARI": st.column_config.NumberColumn(
            "UMUR (HARI)",
            format="%d"
        )
    }
)

# ============================================================
# STATISTIK
# ============================================================
with st.expander("📈 Statistik Lengkap", expanded=False):
    
    # Statistik per WITEL
    st.subheader("Tiket per WITEL")
    witel_stats = df_filtered["WITEL"].value_counts().reset_index()
    witel_stats.columns = ["WITEL", "JUMLAH"]
    st.dataframe(witel_stats, use_container_width=True, hide_index=True)
    
    # Statistik per STATUS
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
    # Download semua data
    csv_all = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Semua Data (CSV)",
        data=csv_all,
        file_name=f"oss_all_data_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        use_container_width=True
    )

with col2:
    # Download data aktif
    df_aktif = df[df["IS_ACTIVE"] == True].copy()
    csv_active = df_aktif.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Data Aktif (CSV)",
        data=csv_active,
        file_name=f"oss_active_data_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        use_container_width=True
    )

# ============================================================
# FOOTER
# ============================================================
st.markdown("---")

st.caption(f"🔄 Auto-refresh setiap 5 menit. Update terakhir: {datetime.now().strftime('%H:%M:%S')}")
