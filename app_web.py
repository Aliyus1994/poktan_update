# -*- coding: utf-8 -*-
"""
SIGA BKKBN Data Explorer - Versi Web (Streamlit).
Letakkan satu folder dengan siga_core.py.

Jalankan lokal:
  pip install streamlit pandas requests
  streamlit run app_web.py
"""

from datetime import datetime
import pandas as pd
import streamlit as st
import siga_core as core

st.set_page_config(
    page_title="SIGA BKKBN - Rekap BKB & BKL",
    page_icon="📊",
    layout="wide",
)

# ---------- gaya tampilan biru-putih ----------
st.markdown(
    """
    <style>
        .header-box {
            background: linear-gradient(90deg, #073B73 0%, #0B5CAD 100%);
            color: #FFFFFF;
            padding: 18px 22px;
            border-radius: 12px;
            margin-bottom: 16px;
        }
        .header-box h2 {
            margin: 0;
            color: #FFFFFF;
            font-size: 1.5rem;
        }
        .header-box p {
            margin: 4px 0 0 0;
            color: #D6E6F8;
            font-size: 0.92rem;
        }
    </style>
    <div class="header-box">
        <h2>SIGA BKKBN</h2>
        <p>Rekap Peserta BKB & Capaian BKL per Kecamatan</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------- inisialisasi state ----------
if "hasil_rekap" not in st.session_state:
    st.session_state.hasil_rekap = None
if "periode_label" not in st.session_state:
    st.session_state.periode_label = ""

# ---------- panel filter ----------
sekarang = datetime.now()
nama_bulan_default = next(
    (k for k, v in core.BULAN.items() if v == sekarang.month),
    "Januari (1)",
)
tahun_default = str(sekarang.year) if str(sekarang.year) in core.TAHUN else "2026"

kab_list = list(core.KABUPATEN_MAPPING.keys())
default_kab_idx = kab_list.index("KOTA BANDAR LAMPUNG") if "KOTA BANDAR LAMPUNG" in kab_list else 0

col1, col2, col3 = st.columns([2.5, 1.5, 1])
with col1:
    kab_nama = st.selectbox(
        "Kabupaten/Kota",
        options=kab_list,
        index=default_kab_idx,
    )
with col2:
    bulan_nama = st.selectbox(
        "Bulan",
        options=list(core.BULAN.keys()),
        index=list(core.BULAN.keys()).index(nama_bulan_default),
    )
with col3:
    tahun_pilih = st.selectbox(
        "Tahun",
        options=core.TAHUN,
        index=core.TAHUN.index(tahun_default),
    )

btn_col1, btn_col2, _ = st.columns([1.4, 1.4, 3])
with btn_col1:
    jalankan = st.button("Jalankan Rekap", type="primary", use_container_width=True)
with btn_col2:
    paksa_refresh = st.checkbox("Abaikan cache master", value=False)

# ---------- eksekusi rekap ----------
if jalankan:
    kab_id = core.KABUPATEN_MAPPING[kab_nama]
    bulan_val = core.BULAN[bulan_nama]
    st.session_state.periode_label = f"{kab_id}_{bulan_val}_{tahun_pilih}"

    if paksa_refresh:
        core.ambil_master(kab_id, paksa=True)

    prog_bar = st.progress(0.0, text="Memulai proses rekap...")
    status_box = st.empty()

    def lapor(selesai, total, teks):
        pct = min(1.0, max(0.0, selesai / max(total, 1)))
        prog_bar.progress(pct, text=teks)
        status_box.info(teks)

    try:
        hasil = core.jalankan_rekap(kab_id, bulan_val, tahun_pilih, lapor)
        st.session_state.hasil_rekap = hasil
        prog_bar.progress(1.0, text="Selesai memproses seluruh poktan.")
        status_box.success(f"Rekap selesai untuk **{kab_nama}** ({bulan_nama} {tahun_pilih}).")
    except Exception as exc:
        st.session_state.hasil_rekap = None
        prog_bar.empty()
        status_box.error(f"Gagal menjalankan rekap: {exc}")

# ---------- tampilkan hasil ----------
hasil = st.session_state.hasil_rekap
if hasil is not None:
    if hasil.get("catatan"):
        st.warning("Catatan: " + " | ".join(hasil["catatan"]))

    rekap_formatted = [
        [
            idx,
            r[0],
            core.fmt_angka(r[1]),
            core.fmt_angka(r[2]),
            core.fmt_persen(r[3]),
            core.fmt_angka(r[4]),
            core.fmt_angka(r[5]),
            core.fmt_persen(r[6]),
        ]
        for idx, r in enumerate(hasil["rekap"], start=1)
    ]
    kol_rekap_tampil = ["No"] + core.KOLOM_REKAP
    df_rekap = pd.DataFrame(rekap_formatted, columns=kol_rekap_tampil)

    detail_formatted = [[idx] + r for idx, r in enumerate(hasil["detail"], start=1)]
    kol_detail_tampil = ["No"] + core.KOLOM_DETAIL
    df_detail = pd.DataFrame(detail_formatted, columns=kol_detail_tampil)

    # Unduh CSV langsung dari browser
    dl1, dl2, _ = st.columns([1.3, 1.3, 4])
    with dl1:
        st.download_button(
            label="Unduh CSV Rekap",
            data=df_rekap.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"rekap_siga_{st.session_state.periode_label}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with dl2:
        st.download_button(
            label="Unduh CSV Detail",
            data=df_detail.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"detail_siga_{st.session_state.periode_label}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    def sorot_bkb(row):
        try:
            persen_bkb = float(str(row["% BKB"]).replace("%", "").strip())
            if persen_bkb > core.AMBANG_BIRU:
                return ["background-color: #0B5CAD; color: #FFFFFF; font-weight: 600;"] * len(row)
        except ValueError:
            pass
        return [""] * len(row)

    tab_rekap, tab_detail = st.tabs(["Rekap Kecamatan", "Detail Poktan"])

    with tab_rekap:
        st.caption(f"Baris biru = % BKB di atas {core.AMBANG_BIRU:.0f}.")
        st.dataframe(
            df_rekap.style.apply(sorot_bkb, axis=1),
            use_container_width=True,
            hide_index=True,
        )

    with tab_detail:
        st.dataframe(
            df_detail,
            use_container_width=True,
            hide_index=True,
        )
