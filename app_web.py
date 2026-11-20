# -*- coding: utf-8 -*-
"""
SIGA BKKBN Data Explorer - Versi Web (Streamlit) dengan Auto-Refresh Latar Belakang.
Letakkan satu folder dengan siga_core.py.

Jalankan lokal:
  pip install streamlit pandas requests
  streamlit run app_web.py
"""

from datetime import datetime
import threading
import time
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


# ---------- background worker lintas rerun ----------
@st.cache_resource
def get_bg_store():
    """Menyimpan state worker latar belakang per sesi agar tidak reset saat rerun."""
    return {}


def dapatkan_worker(session_key):
    store = get_bg_store()
    if session_key not in store:
        store[session_key] = {
            "lock": threading.Lock(),
            "running": False,
            "stop_event": threading.Event(),
            "hasil": None,
            "error": None,
            "last_updated": None,
            "status_bg": "Menunggu...",
            "params": None,
        }
    return store[session_key]


def mulai_background_refresh(worker, kab_id, kab_nama, bulan_val, bulan_nama, tahun_pilih, interval_detik=30):
    """Hentikan worker lama (jika ada) dan mulai loop refresh diam-diam di background."""
    with worker["lock"]:
        # Hentikan thread lama jika masih berjalan
        worker["stop_event"].set()
        stop_event = threading.Event()
        worker["stop_event"] = stop_event
        worker["running"] = True
        worker["error"] = None
        worker["params"] = (kab_id, kab_nama, bulan_val, bulan_nama, tahun_pilih)

    def loop_refresh():
        while not stop_event.is_set():
            # Tunggu selama interval_detik sebelum refresh berikutnya
            if stop_event.wait(timeout=interval_detik):
                break
            try:
                with worker["lock"]:
                    worker["status_bg"] = "Menyegarkan data di latar belakang..."
                hasil_baru = core.jalankan_rekap(kab_id, bulan_val, tahun_pilih, lambda *_: None)
                waktu_str = datetime.now().strftime("%H:%M:%S")
                with worker["lock"]:
                    if not stop_event.is_set():
                        worker["hasil"] = hasil_baru
                        worker["last_updated"] = waktu_str
                        worker["error"] = None
                        worker["status_bg"] = f"Sinkronisasi latar belakang berhasil ({waktu_str})"
            except Exception as exc:
                waktu_str = datetime.now().strftime("%H:%M:%S")
                with worker["lock"]:
                    if not stop_event.is_set():
                        worker["error"] = str(exc)
                        worker["status_bg"] = f"Gagal sinkronisasi latar belakang ({waktu_str})"

        with worker["lock"]:
            worker["running"] = False

    t = threading.Thread(target=loop_refresh, daemon=True)
    t.start()


def hentikan_background_refresh(worker):
    with worker["lock"]:
        worker["stop_event"].set()
        worker["running"] = False
        worker["status_bg"] = "Auto-refresh dihentikan."


# ---------- inisialisasi session state ----------
if "session_uid" not in st.session_state:
    st.session_state.session_uid = f"sess_{id(st.session_state)}_{time.time()}"
if "hasil_rekap" not in st.session_state:
    st.session_state.hasil_rekap = None
if "periode_label" not in st.session_state:
    st.session_state.periode_label = ""
if "auto_refresh_aktif" not in st.session_state:
    st.session_state.auto_refresh_aktif = True
if "last_sync" not in st.session_state:
    st.session_state.last_sync = ""

worker = dapatkan_worker(st.session_state.session_uid)

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

btn_col1, btn_col2, btn_col3, _ = st.columns([1.4, 1.5, 1.6, 2.5])
with btn_col1:
    jalankan = st.button("Jalankan Rekap", type="primary", use_container_width=True)
with btn_col2:
    auto_refresh_ui = st.checkbox(
        "Auto-refresh tiap 30 detik",
        value=st.session_state.auto_refresh_aktif,
    )
with btn_col3:
    paksa_refresh = st.checkbox("Abaikan cache master", value=False)

# Tangani perubahan toggle auto-refresh
if auto_refresh_ui != st.session_state.auto_refresh_aktif:
    st.session_state.auto_refresh_aktif = auto_refresh_ui
    if not auto_refresh_ui:
        hentikan_background_refresh(worker)
    elif st.session_state.hasil_rekap is not None and worker["params"] is not None:
        p = worker["params"]
        mulai_background_refresh(worker, p[0], p[1], p[2], p[3], p[4], interval_detik=30)

# ---------- eksekusi rekap awal ----------
if jalankan:
    kab_id = core.KABUPATEN_MAPPING[kab_nama]
    bulan_val = core.BULAN[bulan_nama]
    st.session_state.periode_label = f"{kab_id}_{bulan_val}_{tahun_pilih}"

    hentikan_background_refresh(worker)

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
        waktu_awal = datetime.now().strftime("%H:%M:%S")
        st.session_state.hasil_rekap = hasil
        st.session_state.last_sync = waktu_awal

        with worker["lock"]:
            worker["hasil"] = hasil
            worker["last_updated"] = waktu_awal
            worker["error"] = None
            worker["params"] = (kab_id, kab_nama, bulan_val, bulan_nama, tahun_pilih)

        prog_bar.progress(1.0, text="Selesai memproses seluruh poktan.")
        status_box.success(f"Rekap selesai untuk **{kab_nama}** ({bulan_nama} {tahun_pilih}).")

        if st.session_state.auto_refresh_aktif:
            mulai_background_refresh(
                worker, kab_id, kab_nama, bulan_val, bulan_nama, tahun_pilih, interval_detik=30
            )
    except Exception as exc:
        st.session_state.hasil_rekap = None
        prog_bar.empty()
        status_box.error(f"Gagal menjalankan rekap: {exc}")


# ---------- area tampilan hasil (auto-poll ringan tiap 5 detik untuk cek hasil background) ----------
@st.fragment(run_every="5s")
def tampilkan_hasil_live():
    with worker["lock"]:
        hasil_bg = worker["hasil"]
        updated_bg = worker["last_updated"]
        status_bg = worker["status_bg"]
        err_bg = worker["error"]
        is_running = worker["running"]
        params = worker["params"]

    if hasil_bg is not None:
        st.session_state.hasil_rekap = hasil_bg
    if updated_bg:
        st.session_state.last_sync = updated_bg

    hasil = st.session_state.hasil_rekap
    if hasil is None:
        return

    # Info status sinkronisasi latar belakang
    if st.session_state.auto_refresh_aktif and is_running and params:
        st.caption(
            f"🟢 Auto-refresh latar belakang aktif (setiap 30 detik) untuk **{params[1]}** "
            f"({params[3]} {params[4]}) | Pembaruan terakhir: **{st.session_state.last_sync}** "
            f"— _{status_bg}_"
        )
    elif st.session_state.last_sync:
        st.caption(f"Pembaruan terakhir: **{st.session_state.last_sync}**")

    if err_bg:
        st.warning(f"Catatan pembaruan latar belakang: {err_bg}")

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
            key=f"dl_rekap_{st.session_state.last_sync}",
        )
    with dl2:
        st.download_button(
            label="Unduh CSV Detail",
            data=df_detail.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"detail_siga_{st.session_state.periode_label}.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"dl_detail_{st.session_state.last_sync}",
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


tampilkan_hasil_live()
