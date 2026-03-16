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
    
    # Konversi ke string
    ttr_str = str(ttr_value).strip()
    
    # Handle format HH:MM:SS
    if ":" in ttr_str:
        parts = ttr_str.split(":")
        if len(parts) == 3:
            try:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = int(parts[2])
                
                # Bulatkan menit (abaikan detik)
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
    Mengubah format 2026-03-01T10:28:22.498 menjadi "1 maret 10:28"
    """
    if pd.isna(date_str) or date_str is None or date_str == "":
        return "-"
    
    try:
        # Handle format ISO dengan T
        date_str = str(date_str)
        if "T" in date_str:
            date_str = date_str.split(".")[0]  # Hapus millisecond
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            dt = pd.to_datetime(date_str)
        
        # Format: 1 maret 10:28
        nama_bulan = ["januari", "februari", "maret", "april", "mei", "juni", 
                      "juli", "agustus", "september", "oktober", "november", "desember"]
        bulan = nama_bulan[dt.month - 1]
        return f"{dt.day} {bulan} {dt.hour:02d}:{dt.minute:02d}"
    except:
        return str(date_str)

# ============================================================
# FUNGSI MEMBUAT KALIMAT
# ============================================================
def buat_kalimat(row):
    """
    Membuat kalimat dengan format:
    SERVICE ID + Enter + Progres sebelumnya : + isi WORKLOG SUMMARY + Enter + Mohon dibantu updatenya kembali 🙏
    """
    service_id = row.get("SERVICE ID", "-") if pd.notna(row.get("SERVICE ID")) else "-"
    worklog = row.get("WORKLOG SUMMARY", "-") if pd.notna(row.get("WORKLOG SUMMARY")) else "-"
    
    # Bersihkan worklog dari karakter aneh
    worklog = str(worklog).replace("\n", " ").replace("\r", " ").strip()
    
    kalimat = f"{service_id}\nProgres sebelumnya : {worklog}\nMohon dibantu updatenya kembali 🙏"
    return kalimat

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
# METRIKS RINGKASAN (DIPINDAHKAN KE DALAM TAB)
# ============================================================
# Kita tidak menampilkan metrik di sini, akan dipindah ke tab

# ============================================================
# MEMBUAT 3 TAB MENU
# ============================================================
tab1, tab2, tab3 = st.tabs(["📂 TIKET OPEN", "📁 TIKET CLOSE", "📥 DOWNLOAD TIKET"])

with tab1:
    # ========================================================
    # METRIKS RINGKASAN DI DALAM TAB TIKET OPEN
    # ========================================================
    df_open = df_display[df_display["IS_ACTIVE"] == True].copy() if "IS_ACTIVE" in df_display.columns else df_display.copy()
    
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    
    with col_m1:
        total_tiket_open = len(df_open)
        st.metric("📋 TOTAL TIKET OPEN", f"{total_tiket_open}")
    
    with col_m2:
        if "LAYANAN" in df_open.columns:
            tsel_open = len(df_open[df_open["LAYANAN"] == "TSEL"])
            olo_open = len(df_open[df_open["LAYANAN"] == "OLO"])
            st.metric("📊 LAYANAN", f"{tsel_open} TSEL", f"{olo_open} OLO")
        else:
            st.metric("📊 LAYANAN", "N/A")
    
    with col_m3:
        # Kosong atau bisa diisi dengan metrik lain
        st.metric(" ", " ")
    
    with col_m4:
        # Kosong atau bisa diisi dengan metrik lain
        st.metric(" ", " ")
    
    st.markdown("---")
    
    # ========================================================
    # FILTER DAN KOTAK KALIMAT
    # ========================================================
    col_filter1, col_filter2, col_filter3 = st.columns([2, 3, 1])
    
    with col_filter1:
        cari_incident_open = st.text_input("🔎 Cari Incident", placeholder="Ketik nomor INC...", key="cari_open")
    
    with col_filter2:
        # Kotak untuk menampilkan kalimat hasil generate
        kalimat_text = st.text_area(
            "📝 Kalimat",
            value="",
            height=70,
            key="kalimat_area",
            label_visibility="collapsed",
            placeholder="Klik salah satu baris untuk generate kalimat..."
        )
    
    with col_filter3:
        # Tombol copy
        copy_button = st.button("📋 Copy", key="copy_btn", use_container_width=True)
        if copy_button and kalimat_text:
            st.write("✅ Tersalin!")
            # Gunakan JavaScript untuk copy ke clipboard
            st.markdown(f"""
            <script>
                navigator.clipboard.writeText(`{kalimat_text}`);
            </script>
            """, unsafe_allow_html=True)
    
    # ========================================================
    # FILTER DATA
    # ========================================================
    df_open_filtered = df_open.copy()
    
    if cari_incident_open and "INCIDENT" in df_open_filtered.columns:
        df_open_filtered = df_open_filtered[df_open_filtered["INCIDENT"].astype(str).str.contains(cari_incident_open, case=False, na=False)]
    
    # ========================================================
    # SIAPKAN DATA UNTUK TABEL
    # ========================================================
    tabel_open = []
    
    for idx, row in df_open_filtered.iterrows():
        # Format TTR CUSTOMER
        ttr_formatted = format_ttr(row.get("TTR CUSTOMER"))
        
        # Format LAST UPDATE WORKLOG
        last_update_formatted = format_last_update(row.get("LAST UPDATE WORKLOG"))
        
        # Buat kalimat untuk tombol generate
        kalimat = buat_kalimat(row)
        
        tabel_open.append({
            "NO": len(tabel_open) + 1,
            "INCIDENT": row.get("INCIDENT", "-"),
            "LAYANAN": row.get("LAYANAN", "-"),
            "SERVICE ID": row.get("SERVICE ID", "-"),
            "WITEL": row.get("WITEL", "-"),
            "TTR CUSTOMER": ttr_formatted,
            "WORKLOG SUMMARY": row.get("WORKLOG SUMMARY", "-"),
            "LAST UPDATE WORKLOG": last_update_formatted,
            "_KALIMAT": kalimat,  # Kolom tersembunyi untuk generate kalimat
            "_RAW_DATA": row  # Data mentah untuk akses lebih lanjut
        })
    
    df_tabel_open = pd.DataFrame(tabel_open)
    
    # ========================================================
    # TAMPILKAN TABEL
    # ========================================================
    if df_tabel_open.empty:
        st.info("Tidak ada tiket open")
    else:
        # Pilih kolom yang akan ditampilkan (tanpa _KALIMAT dan _RAW_DATA)
        kolom_tampil = ["NO", "INCIDENT", "LAYANAN", "SERVICE ID", "WITEL", "TTR CUSTOMER", "WORKLOG SUMMARY", "LAST UPDATE WORKLOG"]
        
        # Tampilkan dataframe dengan styling
        st.dataframe(
            df_tabel_open[kolom_tampil],
            use_container_width=True,
            hide_index=True,
            height=400,  # Batasi tinggi tabel agar tidak terlalu besar
            column_config={
                "NO": st.column_config.NumberColumn(
                    "NO",
                    width="small"
                ),
                "INCIDENT": st.column_config.TextColumn(
                    "INCIDENT",
                    width="medium"
                ),
                "LAYANAN": st.column_config.TextColumn(
                    "LAYANAN",
                    width="small"
                ),
                "SERVICE ID": st.column_config.TextColumn(
                    "SERVICE ID",
                    width="medium"
                ),
                "WITEL": st.column_config.TextColumn(
                    "WITEL",
                    width="small"
                ),
                "TTR CUSTOMER": st.column_config.TextColumn(
                    "TTR CUSTOMER",
                    width="small"
                ),
                "WORKLOG SUMMARY": st.column_config.TextColumn(
                    "WORKLOG SUMMARY",
                    width="large"
                ),
                "LAST UPDATE WORKLOG": st.column_config.TextColumn(
                    "LAST UPDATE",
                    width="small"
                )
            }
        )
        
        # ========================================================
        # JAVASCRIPT UNTUK HANDLE KLICK BARIS
        # ========================================================
        # Kita perlu menambahkan sedikit JavaScript untuk mendeteksi klik pada baris tabel
        # dan mengambil kalimat dari baris yang diklik
        
        # Simpan data kalimat ke session state untuk diakses
        st.session_state["kalimat_list"] = df_tabel_open["_KALIMAT"].tolist()
        
        # Buat selector untuk baris tabel (ini akan di-handle oleh Streamlit rerun)
        st.markdown("""
        <style>
        /* Styling untuk baris tabel agar terlihat clickable */
        .stDataFrame [data-testid="StyledDataFrameDataRow"] {
            cursor: pointer;
        }
        .stDataFrame [data-testid="StyledDataFrameDataRow"]:hover {
            background-color: rgba(128, 128, 128, 0.1);
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Tambahkan instruksi untuk user
        st.caption("💡 Klik pada baris untuk generate kalimat")

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
    kolom_tampil_close = ["INCIDENT", "STATUS", "WITEL", "REPORTED DATE", "SUMMARY", "LAYANAN"]
    kolom_tampil_close = [k for k in kolom_tampil_close if k in df_close.columns]
    
    if df_close.empty:
        st.info("Tidak ada tiket close")
    else:
        st.dataframe(
            df_close[kolom_tampil_close],
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
    
    # Filter data untuk download
    df_download = df_db.copy()
    
    # Terapkan filter tanggal
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
