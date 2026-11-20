# -*- coding: utf-8 -*-
"""
SIGA BKKBN Data Explorer - Versi Web (Streamlit) dengan:
- Auto-Refresh Latar Belakang (setiap 30 detik setelah rekap awal selesai)
- Target Kecamatan Juara 1 (% BKB & % BKL) + highlight + tabel gap menuju peringkat 1
- Notifikasi Telegram otomatis saat kecamatan target yang sempat peringkat 1 tersalip

Letakkan satu folder dengan siga_core.py.
Jalankan lokal:
  pip install streamlit pandas requests
  streamlit run app_web.py
"""

from datetime import datetime
import math
import threading
import time
import pandas as pd
import requests
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
        .target-banner {
            background: #EFF6FF;
            border: 1px solid #93C5FD;
            border-left: 5px solid #0B5CAD;
            padding: 12px 16px;
            border-radius: 10px;
            margin: 8px 0 12px 0;
            color: #0F172A;
        }
    </style>
    <div class="header-box">
        <h2>SIGA BKKBN</h2>
        <p>Rekap Peserta BKB & Capaian BKL per Kecamatan + Pantauan Target Juara 1</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------- helper notifikasi telegram ----------
def kirim_telegram(bot_token: str, chat_id: str, pesan: str):
    """Kirim pesan Telegram. Mengembalikan (sukses: bool, info: str)."""
    token = (bot_token or "").strip()
    cid = (chat_id or "").strip()
    if not token or not cid:
        return False, "Bot Token atau Chat ID Telegram belum diisi."
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": cid, "text": pesan, "parse_mode": "HTML"},
            timeout=12,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            return True, "Terkirim"
        return False, f"HTTP {resp.status_code}: {resp.text[:180]}"
    except Exception as exc:
        return False, str(exc)


def _angka_bersih(val) -> float:
    if isinstance(val, (int, float)):
        return float(val) if not math.isnan(float(val)) else 0.0
    return core.to_num(val)


def hitung_analisis_target(rekap_rows, target_kec: str, kab_nama: str, bulan_nama: str, tahun_pilih: str):
    """
    Menghitung peringkat % BKB dan % BKL untuk target_kec di dalam kab_nama.
    Mengembalikan dict ringkasan + list baris tabel mengejar juara 1.
    """
    if not rekap_rows or not target_kec or target_kec == "(Tidak ada / Pantau semua)":
        return None

    parsed = []
    for r in rekap_rows:
        kec = str(r[0]).strip()
        bkb_cap = _angka_bersih(r[1])
        bkb_tgt = _angka_bersih(r[2])
        bkb_pct = _angka_bersih(r[3])
        bkl_tgt = _angka_bersih(r[4])
        bkl_cap = _angka_bersih(r[5])
        bkl_pct = _angka_bersih(r[6])
        parsed.append({
            "kec": kec,
            "bkb_cap": bkb_cap,
            "bkb_tgt": bkb_tgt,
            "bkb_pct": bkb_pct,
            "bkl_cap": bkl_cap,
            "bkl_tgt": bkl_tgt,
            "bkl_pct": bkl_pct,
        })

    target_item = next((x for x in parsed if x["kec"].upper() == target_kec.upper()), None)
    if target_item is None:
        return None

    rank_bkb = sorted(parsed, key=lambda x: (x["bkb_pct"], x["bkb_cap"]), reverse=True)
    pos_bkb = next((idx + 1 for idx, x in enumerate(rank_bkb) if x["kec"] == target_item["kec"]), len(rank_bkb))
    leader_bkb = rank_bkb[0] if rank_bkb else None

    rank_bkl = sorted(parsed, key=lambda x: (x["bkl_pct"], x["bkl_cap"]), reverse=True)
    pos_bkl = next((idx + 1 for idx, x in enumerate(rank_bkl) if x["kec"] == target_item["kec"]), len(rank_bkl))
    leader_bkl = rank_bkl[0] if rank_bkl else None

    def hitung_kejar_bkb():
        if pos_bkb == 1:
            if len(rank_bkb) > 1:
                runner_up = rank_bkb[1]
                selisih_pct = max(0.0, round(target_item["bkb_pct"] - runner_up["bkb_pct"], 2))
                return (
                    "🏆 Peringkat 1",
                    leader_bkb["kec"],
                    f"{leader_bkb['bkb_pct']:.2f}%",
                    0.0,
                    0,
                    f"Juara 1 (unggul {selisih_pct:.2f}% atas #2: {runner_up['kec']})",
                )
            return ("🏆 Peringkat 1", leader_bkb["kec"], f"{leader_bkb['bkb_pct']:.2f}%", 0.0, 0, "Juara 1")

        if target_item["bkb_tgt"] > 0:
            target_pct_lewati = leader_bkb["bkb_pct"] + 0.01
            butuh_peserta_float = (target_pct_lewati / 100.0) * target_item["bkb_tgt"] - target_item["bkb_cap"]
            butuh_peserta = max(1, int(math.ceil(butuh_peserta_float - 1e-9)))
            pct_setelah_tambah = round(((target_item["bkb_cap"] + butuh_peserta) / target_item["bkb_tgt"]) * 100.0, 2)
            kurang_pct = max(0.0, round(pct_setelah_tambah - target_item["bkb_pct"], 2))
        else:
            butuh_peserta = 0
            kurang_pct = max(0.0, round((leader_bkb["bkb_pct"] + 0.01) - target_item["bkb_pct"], 2))

        if pos_bkb == 2:
            status_teks = f"Kurang ~{butuh_peserta:,} peserta (untuk menyalip {leader_bkb['kec']})"
        else:
            status_teks = f"Posisi #{pos_bkb} | Kurang ~{butuh_peserta:,} peserta salip {leader_bkb['kec']}"
        return (f"#{pos_bkb}", leader_bkb["kec"], f"{leader_bkb['bkb_pct']:.2f}%", kurang_pct, butuh_peserta, status_teks)

    def hitung_kejar_bkl():
        if pos_bkl == 1:
            if len(rank_bkl) > 1:
                runner_up = rank_bkl[1]
                selisih_pct = max(0.0, round(target_item["bkl_pct"] - runner_up["bkl_pct"], 2))
                return (
                    "🏆 Peringkat 1",
                    leader_bkl["kec"],
                    f"{leader_bkl['bkl_pct']:.2f}%",
                    0.0,
                    0,
                    f"Juara 1 (unggul {selisih_pct:.2f}% atas #2: {runner_up['kec']})",
                )
            return ("🏆 Peringkat 1", leader_bkl["kec"], f"{leader_bkl['bkl_pct']:.2f}%", 0.0, 0, "Juara 1")

        if target_item["bkl_tgt"] > 0:
            target_pct_lewati = leader_bkl["bkl_pct"] + 0.01
            butuh_cap_float = (target_pct_lewati / 100.0) * target_item["bkl_tgt"] - target_item["bkl_cap"]
            butuh_cap = max(1, int(math.ceil(butuh_cap_float - 1e-9)))
            pct_setelah_tambah = round(((target_item["bkl_cap"] + butuh_cap) / target_item["bkl_tgt"]) * 100.0, 2)
            kurang_pct = max(0.0, round(pct_setelah_tambah - target_item["bkl_pct"], 2))
        else:
            butuh_cap = 0
            kurang_pct = max(0.0, round((leader_bkl["bkl_pct"] + 0.01) - target_item["bkl_pct"], 2))

        if pos_bkl == 2:
            status_teks = f"Kurang ~{butuh_cap:,} capaian BKL (untuk menyalip {leader_bkl['kec']})"
        else:
            status_teks = f"Posisi #{pos_bkl} | Kurang ~{butuh_cap:,} capaian salip {leader_bkl['kec']}"
        return (f"#{pos_bkl}", leader_bkl["kec"], f"{leader_bkl['bkl_pct']:.2f}%", kurang_pct, butuh_cap, status_teks)

    bkb_rank_str, bkb_lead_kec, bkb_lead_pct, bkb_kurang_pct, bkb_kurang_unit, bkb_status = hitung_kejar_bkb()
    bkl_rank_str, bkl_lead_kec, bkl_lead_pct, bkl_kurang_pct, bkl_kurang_unit, bkl_status = hitung_kejar_bkl()

    tabel_kejar = [
        [
            "Persentase BKB (% BKB)",
            target_item["kec"],
            bkb_rank_str,
            f"{target_item['bkb_pct']:.2f}%",
            f"{bkb_lead_kec} ({bkb_lead_pct})",
            f"+{bkb_kurang_pct:.2f}%",
            f"{bkb_kurang_unit:,} peserta" if bkb_kurang_unit > 0 else "0",
            bkb_status,
        ],
        [
            "Persentase BKL (% BKL)",
            target_item["kec"],
            bkl_rank_str,
            f"{target_item['bkl_pct']:.2f}%",
            f"{bkl_lead_kec} ({bkl_lead_pct})",
            f"+{bkb_kurang_pct:.2f}%",
            f"{bkl_kurang_unit:,} capaian" if bkl_kurang_unit > 0 else "0",
            bkl_status,
        ],
    ]

    return {
        "target_kec": target_item["kec"],
        "kab_nama": kab_nama,
        "periode": f"{bulan_nama} {tahun_pilih}",
        "pos_bkb": pos_bkb,
        "pos_bkl": pos_bkl,
        "leader_bkb": leader_bkb,
        "leader_bkl": leader_bkl,
        "target_item": target_item,
        "tabel_kejar": tabel_kejar,
    }


def cek_dan_kirim_notif_tersalip(worker, analisis, bot_token: str, chat_id: str):
    """
    Pantau transisi status: jika sebelumnya target berada di Peringkat 1 (posisi == 1)
    dan sekarang posisinya > 1 (tersalip), kirim notifikasi Telegram sekali per kejadian tersalip.
    Jika naik lagi ke Peringkat 1, reset flag sehingga jika tersalip lagi akan kirim notif baru.
    """
    if not analisis:
        return

    kec = analisis["target_kec"]
    kab = analisis["kab_nama"]
    periode = analisis["periode"]

    with worker["lock"]:
        prev_state = worker.setdefault("rank_state", {})
        kec_state = prev_state.setdefault(
            kec,
            {
                "bkb_was_1": False,
                "bkl_was_1": False,
                "bkb_alerted_leader": None,
                "bkl_alerted_leader": None,
            },
        )

        # --- Cek BKB ---
        if analisis["pos_bkb"] == 1:
            kec_state["bkb_was_1"] = True
            kec_state["bkb_alerted_leader"] = None
        else:
            leader = analisis["leader_bkb"]
            leader_nama = leader["kec"] if leader else "-"
            leader_pct = leader["bkb_pct"] if leader else 0.0
            target_pct = analisis["target_item"]["bkb_pct"]
            if kec_state["bkb_was_1"] and kec_state["bkb_alerted_leader"] != leader_nama:
                pesan = (
                    "⚠️ <b>PERINGKAT 1 BKB TERSALIP!</b>\n"
                    f"Kabupaten/Kota: <b>{kab}</b>\n"
                    f"Periode: <b>{periode}</b>\n"
                    f"Kecamatan Target: <b>{kec}</b> (turun ke Peringkat #{analisis['pos_bkb']} dengan <b>{target_pct:.2f}%</b>)\n"
                    f"Menyalip ke Peringkat #1: <b>{leader_nama}</b> (<b>{leader_pct:.2f}%</b>)"
                )
                ok, info = kirim_telegram(bot_token, chat_id, pesan)
                kec_state["bkb_was_1"] = False
                kec_state["bkb_alerted_leader"] = leader_nama
                worker["notif_log"] = (
                    f"[BKB] Notif tersalip ke {leader_nama}: {'Berhasil' if ok else 'Gagal (' + info + ')'}"
                )

        # --- Cek BKL ---
        if analisis["pos_bkl"] == 1:
            kec_state["bkl_was_1"] = True
            kec_state["bkl_alerted_leader"] = None
        else:
            leader = analisis["leader_bkl"]
            leader_nama = leader["kec"] if leader else "-"
            leader_pct = leader["bkl_pct"] if leader else 0.0
            target_pct = analisis["target_item"]["bkl_pct"]
            if kec_state["bkl_was_1"] and kec_state["bkl_alerted_leader"] != leader_nama:
                pesan = (
                    "⚠️ <b>PERINGKAT 1 BKL TERSALIP!</b>\n"
                    f"Kabupaten/Kota: <b>{kab}</b>\n"
                    f"Periode: <b>{periode}</b>\n"
                    f"Kecamatan Target: <b>{kec}</b> (turun ke Peringkat #{analisis['pos_bkl']} dengan <b>{target_pct:.2f}%</b>)\n"
                    f"Menyalip ke Peringkat #1: <b>{leader_nama}</b> (<b>{leader_pct:.2f}%</b>)"
                )
                ok, info = kirim_telegram(bot_token, chat_id, pesan)
                kec_state["bkl_was_1"] = False
                kec_state["bkl_alerted_leader"] = leader_nama
                worker["notif_log"] = (
                    f"[BKL] Notif tersalip ke {leader_nama}: {'Berhasil' if ok else 'Gagal (' + info + ')'}"
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
            "rank_state": {},
            "notif_log": "",
        }
    return store[session_key]


def mulai_background_refresh(
    worker,
    kab_id,
    kab_nama,
    bulan_val,
    bulan_nama,
    tahun_pilih,
    target_kec,
    tg_token,
    tg_chat_id,
    interval_detik=30,
):
    """Hentikan worker lama (jika ada) dan mulai loop refresh diam-diam di background."""
    with worker["lock"]:
        worker["stop_event"].set()
        stop_event = threading.Event()
        worker["stop_event"] = stop_event
        worker["running"] = True
        worker["error"] = None
        worker["params"] = (
            kab_id,
            kab_nama,
            bulan_val,
            bulan_nama,
            tahun_pilih,
            target_kec,
            tg_token,
            tg_chat_id,
        )

    def loop_refresh():
        while not stop_event.is_set():
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

                analisis_baru = hitung_analisis_target(
                    hasil_baru.get("rekap", []),
                    target_kec,
                    kab_nama,
                    bulan_nama,
                    tahun_pilih,
                )
                cek_dan_kirim_notif_tersalip(worker, analisis_baru, tg_token, tg_chat_id)
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
if "target_kec_pilih" not in st.session_state:
    st.session_state.target_kec_pilih = "(Tidak ada / Pantau semua)"
if "tg_token" not in st.session_state:
    st.session_state.tg_token = ""
if "tg_chat_id" not in st.session_state:
    st.session_state.tg_chat_id = ""

worker = dapatkan_worker(st.session_state.session_uid)

# ---------- panel filter utama ----------
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

# ---------- pilihan kecamatan target juara 1 + pengaturan telegram ----------
kab_id_aktif = core.KABUPATEN_MAPPING[kab_nama]

opsi_kec = ["(Tidak ada / Pantau semua)"]
try:
    master_cached = core._MASTER.get(kab_id_aktif)
    if master_cached and master_cached.get("kec"):
        kec_dari_master = sorted(set(str(v).strip().upper() for v in master_cached["kec"].values() if v))
        opsi_kec.extend(kec_dari_master)
except Exception:
    pass

if st.session_state.hasil_rekap and st.session_state.hasil_rekap.get("rekap"):
    kec_dari_hasil = [
        str(r[0]).strip().upper()
        for r in st.session_state.hasil_rekap["rekap"]
        if r and str(r[0]).strip()
    ]
    for k in kec_dari_hasil:
        if k not in opsi_kec:
            opsi_kec.append(k)

if st.session_state.target_kec_pilih not in opsi_kec:
    opsi_kec.append(st.session_state.target_kec_pilih)

col_t1, col_t2 = st.columns([2.0, 3.0])
with col_t1:
    target_kec_pilih = st.selectbox(
        "Target Kecamatan Juara 1 (% BKB & % BKL)",
        options=opsi_kec,
        index=opsi_kec.index(st.session_state.target_kec_pilih),
        help="Kecamatan yang ditandai akan di-highlight dan diukur selisih capaiannya menuju Peringkat 1.",
    )
    st.session_state.target_kec_pilih = target_kec_pilih

with col_t2:
    with st.expander("🔔 Notifikasi Telegram (Alert saat Peringkat 1 Tersalip)", expanded=False):
        t_col1, t_col2 = st.columns(2)
        with t_col1:
            tg_token_input = st.text_input(
                "Telegram Bot Token",
                value=st.session_state.tg_token,
                type="password",
                placeholder="123456:ABC-DEF...",
            )
            st.session_state.tg_token = tg_token_input
        with t_col2:
            tg_chat_input = st.text_input(
                "Telegram Chat ID",
                value=st.session_state.tg_chat_id,
                placeholder="-100123456789 atau 12345678",
            )
            st.session_state.tg_chat_id = tg_chat_input

        if st.button("Kirim Tes Notif Telegram"):
            ok_test, info_test = kirim_telegram(
                st.session_state.tg_token,
                st.session_state.tg_chat_id,
                f"✅ Tes Notifikasi SIGA BKKBN aktif untuk <b>{kab_nama}</b>.",
            )
            if ok_test:
                st.success("Pesan tes berhasil dikirim ke Telegram!")
            else:
                st.error(f"Gagal mengirim tes Telegram: {info_test}")

# ---------- tombol aksi ----------
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

if auto_refresh_ui != st.session_state.auto_refresh_aktif:
    st.session_state.auto_refresh_aktif = auto_refresh_ui
    if not auto_refresh_ui:
        hentikan_background_refresh(worker)
    elif st.session_state.hasil_rekap is not None and worker["params"] is not None:
        p = worker["params"]
        mulai_background_refresh(
            worker,
            p[0],
            p[1],
            p[2],
            p[3],
            p[4],
            st.session_state.target_kec_pilih,
            st.session_state.tg_token,
            st.session_state.tg_chat_id,
            interval_detik=30,
        )

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
            worker["params"] = (
                kab_id,
                kab_nama,
                bulan_val,
                bulan_nama,
                tahun_pilih,
                st.session_state.target_kec_pilih,
                st.session_state.tg_token,
                st.session_state.tg_chat_id,
            )

        analisis_awal = hitung_analisis_target(
            hasil.get("rekap", []),
            st.session_state.target_kec_pilih,
            kab_nama,
            bulan_nama,
            tahun_pilih,
        )
        cek_dan_kirim_notif_tersalip(
            worker,
            analisis_awal,
            st.session_state.tg_token,
            st.session_state.tg_chat_id,
        )

        prog_bar.progress(1.0, text="Selesai memproses seluruh poktan.")
        status_box.success(f"Rekap selesai untuk **{kab_nama}** ({bulan_nama} {tahun_pilih}).")

        if st.session_state.auto_refresh_aktif:
            mulai_background_refresh(
                worker,
                kab_id,
                kab_nama,
                bulan_val,
                bulan_nama,
                tahun_pilih,
                st.session_state.target_kec_pilih,
                st.session_state.tg_token,
                st.session_state.tg_chat_id,
                interval_detik=30,
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
        notif_log = worker.get("notif_log", "")

    if hasil_bg is not None:
        st.session_state.hasil_rekap = hasil_bg
    if updated_bg:
        st.session_state.last_sync = updated_bg

    hasil = st.session_state.hasil_rekap
    if hasil is None:
        return

    if st.session_state.auto_refresh_aktif and is_running and params:
        st.caption(
            f"🟢 Auto-refresh latar belakang aktif (setiap 30 detik) untuk **{params[1]}** "
            f"({params[3]} {params[4]}) | Pembaruan terakhir: **{st.session_state.last_sync}** "
            f"— _{status_bg}_"
        )
    elif st.session_state.last_sync:
        st.caption(f"Pembaruan terakhir: **{st.session_state.last_sync}**")

    if notif_log:
        st.info(f"Telegram: {notif_log}")

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

    target_kec_aktif = st.session_state.target_kec_pilih
    analisis = hitung_analisis_target(
        hasil.get("rekap", []),
        target_kec_aktif,
        kab_nama,
        bulan_nama,
        tahun_pilih,
    )

    if analisis is not None:
        st.markdown(
            f"""
            <div class="target-banner">
                <strong>🎯 Pantauan Target Juara 1: {analisis['target_kec']}</strong> ({analisis['kab_nama']} — {analisis['periode']})<br/>
                Peringkat % BKB saat ini: <b>#{analisis['pos_bkb']}</b> ({analisis['target_item']['bkb_pct']:.2f}%) |
                Peringkat % BKL saat ini: <b>#{analisis['pos_bkl']}</b> ({analisis['target_item']['bkl_pct']:.2f}%)
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.subheader(f"📈 Tabel Mengejar Peringkat 1 — {analisis['target_kec']}")
        kol_kejar = [
            "Indikator",
            "Kecamatan Target",
            "Peringkat Saat Ini",
            "Capaian % Saat Ini",
            "Pemimpin (#1) Saat Ini",
            "Kurang % Menuju #1",
            "Estimasi Kurang Capaian/Peserta",
            "Keterangan",
        ]
        df_kejar = pd.DataFrame(analisis["tabel_kejar"], columns=kol_kejar)
        st.dataframe(df_kejar, use_container_width=True, hide_index=True)

    def sorot_baris_rekap(row):
        nama_kec_row = str(row.get("Nama Kecamatan", "")).strip().upper()
        is_target = bool(target_kec_aktif) and target_kec_aktif != "(Tidak ada / Pantau semua)" and nama_kec_row == target_kec_aktif.strip().upper()

        try:
            persen_bkb = float(str(row["% BKB"]).replace("%", "").strip())
            di_atas_ambang = persen_bkb > core.AMBANG_BIRU
        except ValueError:
            di_atas_ambang = False

        styles = []
        for col_name in row.index:
            if is_target and col_name == "Nama Kecamatan":
                styles.append("background-color: #FEF08A; color: #713F12; font-weight: 800; border: 2px solid #CA8A04;")
            elif is_target:
                styles.append("background-color: #FEF9C3; color: #1E293B; font-weight: 600;")
            elif di_atas_ambang:
                styles.append("background-color: #0B5CAD; color: #FFFFFF; font-weight: 600;")
            else:
                styles.append("")
        return styles

    tab_rekap, tab_detail = st.tabs(["Rekap Kecamatan", "Detail Poktan"])

    with tab_rekap:
        ket_highlight = f"Baris biru = % BKB di atas {core.AMBANG_BIRU:.0f}."
        if analisis is not None:
            ket_highlight += f" Kolom kuning tegas pada **Nama Kecamatan** = kecamatan target pantauan (**{analisis['target_kec']}**)."
        st.caption(ket_highlight)
        st.dataframe(
            df_rekap.style.apply(sorot_baris_rekap, axis=1),
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
