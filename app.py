import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import time
import re
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
# CSS UNTUK MEMPERKECIL FONT DAN SPASI METRIK
# ============================================================
st.markdown("""
<style>
    /* Perkecil font metric */
    [data-testid="stMetric"] {
        background-color: transparent;
        padding: 0px !important;
        margin: 0px !important;
    }
    
    [data-testid="stMetricLabel"] {
        font-size: 0.7rem !important;
        font-weight: normal !important;
        margin-bottom: -5px !important;
    }
    
    [data-testid="stMetricValue"] {
        font-size: 1.2rem !important;
        line-height: 1.2 !important;
    }
    
    [data-testid="stMetricDelta"] {
        font-size: 0.6rem !important;
    }
    
    /* Kurangi padding kolom */
    .st-emotion-cache-1r6slb0 {
        padding: 0.5rem !important;
    }
    
    /* Perkecil jarak antar kolom */
    .st-emotion-cache-ocqkz7 {
        gap: 0.2rem !important;
    }
    
    /* Perkecil jarak di dalam expander */
    .st-emotion-cache-1rsyhus {
        padding: 0.5rem !important;
    }
    
    /* Warna untuk severity */
    .severity-premium {
        color: #FF4B4B !important;
        font-weight: bold;
    }
    .severity-critical {
        color: #FF6B6B !important;
        font-weight: bold;
    }
    .severity-major {
        color: #FFA500 !important;
        font-weight: bold;
    }
    .severity-minor {
        color: #FFD700 !important;
        font-weight: bold;
    }
    .severity-low {
        color: #00C851 !important;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

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
# FUNGSI MEMBACA DATA DARI SUPABASE
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
        records = df.to_dict('records')
        
        # Bersihkan nilai yang tidak bisa di-JSON
        for record in records:
            for key, value in list(record.items()):
                if pd.isna(value):
                    record[key] = None
                elif isinstance(value, pd.Timestamp):
                    record[key] = value.isoformat() if pd.notna(value) else None
        
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
# FUNGSI EKSTRAK SEVERITY DARI SUMMARY
# ============================================================
def ekstrak_severity(summary):
    """
    Mengekstrak severity (LOW, MINOR, MAJOR, CRITICAL, PREMIUM) dari SUMMARY
    """
    if pd.isna(summary) or summary is None or summary == "":
        return "-"
    
    summary_str = str(summary).upper()
    
    severity_list = ["PREMIUM", "CRITICAL", "MAJOR", "MINOR", "LOW"]
    
    for severity in severity_list:
        if severity in summary_str:
            return severity
    
    return "-"

# ============================================================
# FUNGSI EKSTRAK JUMLAH SITE DARI SUMMARY
# ============================================================
def ekstrak_jumlah_site(summary):
    """
    Mengekstrak jumlah site dari SUMMARY
    Contoh:
    - "4NODEB" -> 4
    - "9NODEB" -> 9
    - "117BTS" -> 117
    - Jika tidak ada pola, default 1
    """
    if pd.isna(summary) or summary is None or summary == "":
        return 1
    
    summary_str = str(summary).upper()
    
    # Cari pola seperti 4NODEB, 9NODEB, 117BTS, dll
    pattern = r'(\d+)(?:NODEB|BTS)'
    match = re.search(pattern, summary_str)
    
    if match:
        return int(match.group(1))
    
    # Jika ada kata "SITE" diikuti angka (jarang terjadi)
    pattern2 = r'SITE[:\s]*(\d+)'
    match2 = re.search(pattern2, summary_str)
    if match2:
        return int(match2.group(1))
    
    # Default: 1 site
    return 1

# ============================================================
# FUNGSI FORMAT TTR CUSTOMER
# ============================================================
def format_ttr(ttr_value):
    """
    Mengubah format TTR CUSTOMER dari HH:MM:SS menjadi:
    - < 24 jam: "X jam Y menit"
    - > 24 jam: "X hari Y jam Z menit"
    """
    if pd.isna(ttr_value) or ttr_value is None or ttr_value == "":
        return "-"
    
    ttr_str = str(ttr_value).strip()
    
    if ":" in ttr_str:
        parts = ttr_str.split(":")
        if len(parts) == 3:
            try:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = int(parts[2])
                
                if seconds >= 30:
                    minutes += 1
                if minutes >= 60:
                    hours += 1
                    minutes -= 60
                
                if hours < 24:
                    return f"{hours} jam {minutes} menit"
                else:
                    days = hours // 24
                    remaining_hours = hours % 24
                    return f"{days} hari {remaining_hours} jam {minutes} menit"
            except:
                return ttr_str
    
    return ttr_str

# ============================================================
# FUNGSI FORMAT LAST UPDATE WORKLOG
# ============================================================
def format_last_update(date_str):
    """
    Mengubah format 2026-03-01T10:28:22.498 menjadi "01 Maret, Pukul 10:28"
    """
    if pd.isna(date_str) or date_str is None or date_str == "":
        return "-"
    
    try:
        date_str = str(date_str)
        if "T" in date_str:
            date_str = date_str.split(".")[0]
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            dt = pd.to_datetime(date_str)
        
        nama_bulan = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", 
                      "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
        bulan = nama_bulan[dt.month - 1]
        return f"{dt.day:02d} {bulan}, Pukul {dt.hour:02d}:{dt.minute:02d}"
    except:
        return str(date_str)

# ============================================================
# FUNGSI MEMPROSES DATA
# ============================================================
def process_data(df):
    """Membersihkan data dan menambah kolom analisis"""
    df = df.copy()
    
    unnamed_cols = [col for col in df.columns if 'Unnamed' in col or col == '']
    if unnamed_cols:
        df = df.drop(columns=unnamed_cols)
    
    df.columns = (
        df.columns
        .str.strip()
        .str.replace('"', '', regex=False)
    )
    
    if "INCIDENT" in df.columns:
        df = df.drop_duplicates(subset=["INCIDENT"], keep="first")
    
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
    
    # Buat kolom SEVERITY
    if "SUMMARY" in df.columns:
        df["SEVERITY"] = df["SUMMARY"].apply(ekstrak_severity)
    else:
        df["SEVERITY"] = "-"
    
    # Buat kolom IMPACT (JUMLAH SITE)
    if "SUMMARY" in df.columns:
        df["IMPACT"] = df["SUMMARY"].apply(ekstrak_jumlah_site)
    else:
        df["IMPACT"] = 1
    
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
                    st.rerun()
                else:
                    st.error("❌ Gagal menyimpan ke Supabase")
            else:
                st.error(msg)

# ============================================================
# LOAD DATA DARI SUPABASE
# ============================================================
with st.spinner("Memuat data..."):
    df_db = load_data_from_supabase()

if df_db.empty:
    st.warning("⚠️ Belum ada data. Silakan upload CSV terlebih dahulu.")
    st.info("📤 Klik tombol 'Browse files' di pojok kanan atas untuk upload")
    st.stop()

# Proses data untuk menambah kolom analisis
df_display = process_data(df_db)

# ============================================================
# MEMBUAT 3 TAB MENU
# ============================================================
tab1, tab2, tab3 = st.tabs(["📂 TIKET OPEN", "📁 TIKET CLOSE", "📥 DOWNLOAD TIKET"])

with tab1:
    # ========================================================
    # METRIKS RINGKASAN (DALAM 1 BARIS)
    # ========================================================
    df_open = df_display[df_display["IS_ACTIVE"] == True].copy() if "IS_ACTIVE" in df_display.columns else df_display.copy()
    
    # Hitung severity counts
    severity_counts = {}
    if "SEVERITY" in df_open.columns:
        for sev in ["PREMIUM", "CRITICAL", "MAJOR", "MINOR", "LOW"]:
            severity_counts[sev] = len(df_open[df_open["SEVERITY"] == sev])
    
    # Tampilkan semua metrik dalam 1 baris (7 kolom)
    cols = st.columns(7)
    
    with cols[0]:
        st.metric("📋 TOTAL", f"{len(df_open)}")
    
    with cols[1]:
        if "LAYANAN" in df_open.columns:
            tsel_open = len(df_open[df_open["LAYANAN"] == "TSEL"])
            olo_open = len(df_open[df_open["LAYANAN"] == "OLO"])
            st.metric("📊 LAYANAN", f"{tsel_open}|{olo_open}", help="TSEL | OLO")
        else:
            st.metric("📊 LAYANAN", "N/A")
    
    with cols[2]:
        st.metric("🔴 PREMIUM", severity_counts.get("PREMIUM", 0))
    
    with cols[3]:
        st.metric("🔥 CRITICAL", severity_counts.get("CRITICAL", 0))
    
    with cols[4]:
        st.metric("⚠️ MAJOR", severity_counts.get("MAJOR", 0))
    
    with cols[5]:
        st.metric("🟡 MINOR", severity_counts.get("MINOR", 0))
    
    with cols[6]:
        st.metric("🟢 LOW", severity_counts.get("LOW", 0))
    
    st.markdown("---")
    
    # ========================================================
    # FILTER
    # ========================================================
    col_filter1, col_filter2, col_filter3 = st.columns([1, 1, 1])
    
    with col_filter1:
        cari_incident_open = st.text_input("🔎 Cari Incident", placeholder="Ketik nomor INC...", key="cari_open")
    
    with col_filter2:
        if "SEVERITY" in df_open.columns:
            semua_severity = sorted(df_open["SEVERITY"].unique())
            pilih_severity = st.multiselect("Filter Severity", semua_severity, default=[], key="severity_filter")
        else:
            pilih_severity = []
    
    with col_filter3:
        if "WITEL" in df_open.columns:
            semua_witel = sorted(df_open["WITEL"].dropna().unique())
            pilih_witel = st.multiselect("Filter WITEL", semua_witel, default=[], key="witel_filter")
        else:
            pilih_witel = []
    
    # ========================================================
    # FILTER DATA
    # ========================================================
    df_open_filtered = df_open.copy()
    
    if cari_incident_open and "INCIDENT" in df_open_filtered.columns:
        df_open_filtered = df_open_filtered[df_open_filtered["INCIDENT"].astype(str).str.contains(cari_incident_open, case=False, na=False)]
    
    if pilih_severity and "SEVERITY" in df_open_filtered.columns:
        df_open_filtered = df_open_filtered[df_open_filtered["SEVERITY"].isin(pilih_severity)]
    
    if pilih_witel and "WITEL" in df_open_filtered.columns:
        df_open_filtered = df_open_filtered[df_open_filtered["WITEL"].isin(pilih_witel)]
    
    # ========================================================
    # SIAPKAN DATA UNTUK TABEL
    # ========================================================
    tabel_open = []
    
    for idx, row in df_open_filtered.iterrows():
        ttr_formatted = format_ttr(row.get("TTR CUSTOMER"))
        last_update_formatted = format_last_update(row.get("LAST UPDATE WORKLOG"))
        
        # Tentukan class severity untuk warna
        severity_class = ""
        if row.get("SEVERITY") == "PREMIUM":
            severity_class = "severity-premium"
        elif row.get("SEVERITY") == "CRITICAL":
            severity_class = "severity-critical"
        elif row.get("SEVERITY") == "MAJOR":
            severity_class = "severity-major"
        elif row.get("SEVERITY") == "MINOR":
            severity_class = "severity-minor"
        elif row.get("SEVERITY") == "LOW":
            severity_class = "severity-low"
        
        tabel_open.append({
            "NO": len(tabel_open) + 1,
            "INCIDENT": row.get("INCIDENT", "-"),
            "LAYANAN": row.get("LAYANAN", "-"),
            "SERVICE ID": row.get("SERVICE ID", "-"),
            "SEVERITY": f'<span class="{severity_class}">{row.get("SEVERITY", "-")}</span>',
            "IMPACT": row.get("IMPACT", 1),
            "WITEL": row.get("WITEL", "-"),
            "TTR CUSTOMER": ttr_formatted,
            "WORKLOG SUMMARY": row.get("WORKLOG SUMMARY", "-"),
            "LAST UPDATE WORKLOG": last_update_formatted
        })
    
    df_tabel_open = pd.DataFrame(tabel_open)
    
    # ========================================================
    # TAMPILKAN TABEL (HANYA DATA YANG ADA)
    # ========================================================
    if df_tabel_open.empty:
        st.info("Tidak ada tiket open")
    else:
        st.write("### 📋 Daftar Tiket Open")
        
        # Tampilkan tabel dengan HTML untuk warna
        for idx, row in df_tabel_open.iterrows():
            cols = st.columns([0.5, 1.5, 0.8, 1.5, 1, 0.5, 1, 1.5, 1.5, 1])
            
            cols[0].write(f"**{row['NO']}**")
            cols[1].write(row['INCIDENT'])
            cols[2].write(row['LAYANAN'])
            cols[3].write(row['SERVICE ID'])
            cols[4].markdown(row['SEVERITY'], unsafe_allow_html=True)
            cols[5].write(row['IMPACT'])
            cols[6].write(row['WITEL'])
            cols[7].write(row['TTR CUSTOMER'])
            
            # WORKLOG SUMMARY dengan wrap text
            worklog = str(row['WORKLOG SUMMARY'])
            if len(worklog) > 50:
                worklog = worklog[:50] + "..."
            cols[8].write(worklog)
            
            cols[9].write(row['LAST UPDATE WORKLOG'])
            
            st.markdown("---")

with tab2:
    st.subheader("🔍 Tiket Close (Status Tidak Aktif)")
    
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
    
    df_close = df_display[df_display["IS_ACTIVE"] == False].copy() if "IS_ACTIVE" in df_display.columns else pd.DataFrame()
    
    if not df_close.empty:
        if pilih_witel_close and "WITEL" in df_close.columns:
            df_close = df_close[df_close["WITEL"].isin(pilih_witel_close)]
        if pilih_layanan_close and "LAYANAN" in df_close.columns:
            df_close = df_close[df_close["LAYANAN"].isin(pilih_layanan_close)]
        if cari_incident_close and "INCIDENT" in df_close.columns:
            df_close = df_close[df_close["INCIDENT"].astype(str).str.contains(cari_incident_close, case=False, na=False)]
    
    # Siapkan tabel untuk tiket close
    tabel_close = []
    for idx, row in df_close.iterrows():
        tabel_close.append({
            "NO": len(tabel_close) + 1,
            "INCIDENT": row.get("INCIDENT", "-"),
            "LAYANAN": row.get("LAYANAN", "-"),
            "SERVICE ID": row.get("SERVICE ID", "-"),
            "SEVERITY": row.get("SEVERITY", "-"),
            "IMPACT": row.get("IMPACT", 1),
            "WITEL": row.get("WITEL", "-"),
            "STATUS": row.get("STATUS", "-"),
            "REPORTED DATE": row.get("REPORTED DATE", "-")
        })
    
    df_tabel_close = pd.DataFrame(tabel_close)
    
    if df_tabel_close.empty:
        st.info("Tidak ada tiket close")
    else:
        kolom_tampil_close = ["NO", "INCIDENT", "LAYANAN", "SERVICE ID", "SEVERITY", "IMPACT", "WITEL", "STATUS", "REPORTED DATE"]
        st.dataframe(
            df_tabel_close[kolom_tampil_close],
            use_container_width=True,
            hide_index=True
        )
        st.caption(f"Menampilkan {len(df_tabel_close)} tiket close")

with tab3:
    st.subheader("📥 Download Tiket (Semua Kolom)")
    
    col_d1, col_d2, col_d3, col_d4 = st.columns(4)
    
    with col_d1:
        if "REPORTED DATE" in df_display.columns:
            df_temp = df_display.copy()
            df_temp["REPORTED DATE"] = pd.to_datetime(df_temp["REPORTED DATE"])
            min_date = df_temp["REPORTED DATE"].min().date()
            max_date = df_temp["REPORTED DATE"].max().date()
            tgl_mulai = st.date_input("Dari Tanggal", min_date, key="tgl_mulai")
        else:
            tgl_mulai = None
    
    with col_d2:
        if "REPORTED DATE" in df_display.columns:
            tgl_akhir = st.date_input("Sampai Tanggal", max_date, key="tgl_akhir")
        else:
            tgl_akhir = None
    
    with col_d3:
        if "WITEL" in df_display.columns:
            semua_witel = sorted(df_display["WITEL"].dropna().unique())
            pilih_witel_download = st.multiselect("Pilih WITEL", semua_witel, default=[], key="witel_download")
        else:
            pilih_witel_download = []
    
    with col_d4:
        if "LAYANAN" in df_display.columns:
            semua_layanan = sorted(df_display["LAYANAN"].unique())
            pilih_layanan_download = st.multiselect("Pilih LAYANAN", semua_layanan, default=[], key="layanan_download")
        else:
            pilih_layanan_download = []
    
    df_download = df_db.copy()
    
    if "REPORTED DATE" in df_download.columns and tgl_mulai and tgl_akhir:
        df_download["REPORTED DATE"] = pd.to_datetime(df_download["REPORTED DATE"])
        mask_tanggal = (df_download["REPORTED DATE"].dt.date >= tgl_mulai) & (df_download["REPORTED DATE"].dt.date <= tgl_akhir)
        df_download = df_download[mask_tanggal]
    
    if pilih_witel_download and "WITEL" in df_download.columns:
        df_download = df_download[df_download["WITEL"].isin(pilih_witel_download)]
    
    if pilih_layanan_download and "LAYANAN" in df_download.columns:
        df_download = df_download[df_download["LAYANAN"].isin(pilih_layanan_download)]
    
    st.caption(f"Menampilkan {len(df_download)} tiket")
    
    if df_download.empty:
        st.info("Tidak ada data dengan filter yang dipilih")
    else:
        st.dataframe(
            df_download,
            use_container_width=True,
            hide_index=True
        )
        
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
