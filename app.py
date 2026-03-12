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
# FUNGSI MEMBACA DATA DARI SUPABASE
# ============================================================
@st.cache_data(ttl=300)  # Cache 5 menit
def load_data_from_supabase():
    """Membaca semua data dari tabel oss_data"""
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    
    try:
        response = supabase.table('oss_data').select('*').execute()
        df = pd.DataFrame(response.data)
        
        # Hapus kolom internal database yang tidak perlu ditampilkan
        if 'id' in df.columns:
            df = df.drop(columns=['id'])
        if 'created_at' in df.columns:
            df = df.drop(columns=['created_at'])
            
        return df
        
    except Exception as e:
        st.error(f"Gagal baca data: {str(e)}")
        return pd.DataFrame()

# ============================================================
# FUNGSI MENYIMPAN DATA KE SUPABASE (UPSERT)
# ============================================================
def save_to_supabase(df):
    """
    Menyimpan DataFrame ke tabel oss_data
    Jika incident sudah ada, akan di-update
    """
    supabase = init_supabase()
    if supabase is None:
        return False
    
    try:
        # Siapkan data untuk dikirim
        records = df.to_dict('records')
        
        # Bersihkan data: ganti NaN, NaT, infinity dengan None
        for record in records:
            for key, value in list(record.items()):
                # Hapus kolom internal
                if key in ['id', 'created_at']:
                    del record[key]
                    continue
                
                # Ganti nilai yang tidak bisa di-JSON
                if pd.isna(value):  # NaN, NaT, None
                    record[key] = None
                elif isinstance(value, float) and (value == float('inf') or value == float('-inf')):
                    record[key] = None
                elif isinstance(value, pd.Timestamp):
                    record[key] = value.isoformat() if pd.notna(value) else None
        
        # Upsert berdasarkan kolom 'incident' (primary key)
        response = supabase.table('oss_data').upsert(records, on_conflict='incident').execute()
        
        return True
        
    except Exception as e:
        st.error(f"Gagal simpan data: {str(e)}")
        # Untuk debugging
        print(f"Error detail: {str(e)}")
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
    Menambahkan kolom-kolom analisis dan menyiapkan untuk database
    """
    df = df.copy()
    
    # Bersihkan nama kolom
    df.columns = (
        df.columns
        .str.strip()
        .str.replace('"', '', regex=False)
    )
    
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
    
        # Mapping nama kolom dari CSV ke database (perhatikan: database pakai lowercase tanpa spasi)
    kolom_mapping = {
        "INCIDENT": "incident",
        "STATUS": "status",
        "WITEL": "witel",
        "REPORTED DATE": "reported_date",
        "SUMMARY": "summary",
        "TTR CUSTOMER": "ttr_customer",
        "OWNER GROUP": "owner_group",
        "OWNER": "owner",
        "CUSTOMER SEGMENT": "customer_segment",
        "SERVICE TYPE": "service_type",
        "WORKZONE": "workzone",
        "STATUS DATE": "status_date",
        "TICKET ID GAMAS": "ticket_id_gamas",
        "REPORTED BY": "reported_by",
        "CONTACT PHONE": "contact_phone",
        "CONTACT NAME": "contact_name",
        "CONTACT EMAIL": "contact_email",
        "BOOKING DATE": "booking_date",  # <- INI YANG DIPERBAIKI (tanpa spasi, lowercase)
        "DESCRIPTION ASSIGMENT": "description_assigment",
        "REPORTED PRIORITY": "reported_priority",
        "SOURCE TICKET": "source_ticket",
        "SUBSIDIARY": "subsidiary",
        "EXTERNAL TICKET ID": "external_ticket_id",
        "CHANNEL": "channel",
        "CUSTOMER TYPE": "customer_type",
        "CLOSED BY": "closed_by",
        "CLOSED / REOPEN BY": "closed_reopen_by",
        "CUSTOMER ID": "customer_id",
        "CUSTOMER NAME": "customer_name",
        "SERVICE ID": "service_id",
        "SERVICE NO": "service_no",
        "SLG": "slg",
        "TECHNOLOGY": "technology",
        "LAPUL": "lapul",
        "GAUL": "gaul",
        "ONU RX": "onu_rx",
        "PENDING REASON": "pending_reason",
        "DATEMODIFIED": "date_modified",
        "INCIDENT DOMAIN": "incident_domain",
        "REGION": "region",
        "SYMPTOM": "symptom",
        "HIERARCHY PATH": "hierarchy_path",
        "SOLUTION": "solution",
        "DESCRIPTION ACTUAL SOLUTION": "description_actual_solution",
        "KODE PRODUK": "kode_produk",
        "PERANGKAT": "perangkat",
        "TECHNICIAN": "technician",
        "DEVICE NAME": "device_name",
        "WORKLOG SUMMARY": "worklog_summary",
        "LAST UPDATE WORKLOG": "last_update_worklog",
        "CLASSIFICATION FLAG": "classification_flag",
        "REALM": "realm",
        "RELATED TO GAMAS": "related_to_gamas",
        "TSC RESULT": "tsc_result",
        "SCC RESULT": "scc_result",
        "TTR AGENT": "ttr_agent",
        "TTR MITRA": "ttr_mitra",
        "TTR NASIONAL": "ttr_nasional",
        "TTR PENDING": "ttr_pending",
        "TTR REGION": "ttr_region",
        "TTR WITEL": "ttr_witel",
        "TTR END TO END": "ttr_end_to_end",
        "NOTE": "note",
        "GUARANTE STATUS": "guarant_status",
        "RESOLVE DATE": "resolve_date",
        "SN ONT": "sn_ont",
        "TIPE ONT": "tipe_ont",
        "MANUFACTURE ONT": "manufacture_ont",
        "IMPACTED SITE": "impacted_site",
        "CAUSE": "cause",
        "RESOLUTION": "resolution",
        "NOTES ESKALASI": "notes_eskalasi",
        "RK INFORMATION": "rk_information",
        "EXTERNAL TICKET TIER 3": "external_ticket_tier_3",
        "CUSTOMER CATEGORY": "customer_category",
        "CLASSIFICATION PATH": "classification_path",
        "TERITORY NEAR END": "territory_near_end",
        "TERITORY FAR END": "territory_far_end",
        "URGENCY": "urgency",
        "URGENCY DESCRIPTION": "urgency_description",
        "c_street_address": "c_street_address",
        "C_PARENT_ID": "c_parent_id",
        "LAYANAN": "layanan",
        "UMUR_TIKET_HARI": "umur_tiket_hari",
        "IS_ACTIVE": "is_active"
    }
    # Buat kolom baru sesuai mapping
    for old_col, new_col in kolom_mapping.items():
        if old_col in df.columns:
            df[new_col] = df[old_col]
        elif new_col not in df.columns:
            df[new_col] = None
    
    return df

# ============================================================
# TAMPILAN UTAMA DASHBOARD
# ============================================================

# Header dan Upload
col1, col2 = st.columns([8, 2])

with col1:
    st.title("📊 OSS Monitoring Dashboard")
    st.caption("Data tersimpan otomatis di Supabase")

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
                
                # Simpan ke Supabase
                if save_to_supabase(df_upload):
                    st.success(f"✅ Berhasil upload {len(df_upload)} tiket!")
                    st.balloons()
                    st.cache_data.clear()  # Hapus cache
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
    st.warning("Belum ada data. Silakan upload CSV terlebih dahulu.")
    st.stop()

# ============================================================
# SIAPKAN DATA UNTUK DITAMPILKAN
# ============================================================
df_display = df_db.copy()
kolom_tampil_rename = {
    "incident": "INCIDENT",
    "status": "STATUS",
    "witel": "WITEL",
    "reported_date": "REPORTED DATE",
    "summary": "SUMMARY",
    "layanan": "LAYANAN",
    "umur_tiket_hari": "UMUR_TIKET_HARI",
    "is_active": "IS_ACTIVE"
}

for db_col, display_col in kolom_tampil_rename.items():
    if db_col in df_display.columns:
        df_display[display_col] = df_display[db_col]

# Konversi reported_date ke format string
if "REPORTED DATE" in df_display.columns:
    df_display["REPORTED DATE"] = pd.to_datetime(df_display["REPORTED DATE"]).dt.strftime('%Y-%m-%d')

# ============================================================
# METRIKS RINGKASAN
# ============================================================
st.markdown("---")

col1, col2, col3, col4 = st.columns(4)

with col1:
    total_tiket = len(df_display)
    aktif = len(df_display[df_display["IS_ACTIVE"] == True]) if "IS_ACTIVE" in df_display.columns else 0
    st.metric(
        label="📋 TOTAL TIKET",
        value=f"{total_tiket}",
        delta=f"{aktif} aktif"
    )

with col2:
    if "LAYANAN" in df_display.columns:
        tsel = len(df_display[df_display["LAYANAN"] == "TSEL"])
        olo = len(df_display[df_display["LAYANAN"] == "OLO"])
    else:
        tsel = olo = 0
    st.metric(
        label="📊 BERDASARKAN LAYANAN",
        value=f"{tsel} TSEL",
        delta=f"{olo} OLO"
    )

with col3:
    if "UMUR_TIKET_HARI" in df_display.columns:
        umur_rata = df_display["UMUR_TIKET_HARI"].mean()
        if pd.notna(umur_rata):
            st.metric(
                label="⏳ UMUR RATA-RATA",
                value=f"{umur_rata:.1f} hari"
            )
        else:
            st.metric(label="⏳ UMUR RATA-RATA", value="N/A")
    else:
        st.metric(label="⏳ UMUR RATA-RATA", value="N/A")

with col4:
    if "STATUS" in df_display.columns:
        status_counts = df_display["STATUS"].value_counts()
        top_status = status_counts.index[0] if not status_counts.empty else "-"
        st.metric(
            label="⚡ STATUS TERBANYAK",
            value=f"{top_status}",
            delta=f"{status_counts.iloc[0] if not status_counts.empty else 0} tiket"
        )
    else:
        st.metric(label="⚡ STATUS TERBANYAK", value="-")

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
            st.info("Kolom WITEL tidak tersedia")
    
    with col2:
        if "STATUS" in df_display.columns:
            semua_status = sorted(df_display["STATUS"].dropna().unique())
            pilih_status = st.multiselect("Pilih STATUS", semua_status, default=[])
        else:
            pilih_status = []
            st.info("Kolom STATUS tidak tersedia")
    
    with col3:
        if "LAYANAN" in df_display.columns:
            semua_layanan = sorted(df_display["LAYANAN"].unique())
            pilih_layanan = st.multiselect("Pilih LAYANAN", semua_layanan, default=[])
        else:
            pilih_layanan = []
            st.info("Kolom LAYANAN tidak tersedia")
    
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
    if "WITEL" in df_filtered.columns:
        st.subheader("Tiket per WITEL")
        witel_stats = df_filtered["WITEL"].value_counts().reset_index()
        witel_stats.columns = ["WITEL", "JUMLAH"]
        st.dataframe(witel_stats, use_container_width=True, hide_index=True)
    
    # Statistik per STATUS
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
    # Download semua data
    csv_all = df_display.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Semua Data (CSV)",
        data=csv_all,
        file_name=f"oss_all_data_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        use_container_width=True
    )

with col2:
    # Download data aktif
    if "IS_ACTIVE" in df_display.columns:
        df_aktif = df_display[df_display["IS_ACTIVE"] == True].copy()
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


