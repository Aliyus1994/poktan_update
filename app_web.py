code_str = '''# -*- coding: utf-8 -*-
"""
SIGA BKKBN Data Explorer - Versi Web (Streamlit) dengan:
- Auto-Refresh Latar Belakang (setiap 30 detik setelah rekap awal selesai)
- Target Kecamatan Juara 1 (% BKB & % BKL) + highlight seluruh baris + tabel capaian mengejar juara 1
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


def ambil_daftar_kecamatan(kab_id: str, hasil_rekap=None) -> list:
    """
    Mengambil daftar unik nama kecamatan dari master (jika ada), hasil rekap,
    atau langsung dari API master SIGA BKKBN agar dropdown selalu terisi.
    """
    kec_set = []

    def _tambah(nama):
        bersih = str(nama or "").strip().upper()
        if bersih and bersih not in kec_set:
            kec_set.append(bersih)

    # 1. Dari cache _MASTER di siga_core jika sudah tersedia
    try:
        master_cached = getattr(core, "_MASTER", {}).get(kab_id)
        if isinstance(master_cached, dict):
            kec_map = master_cached.get("kec")
            if isinstance(kec_map, dict):
                for v in kec_map.values():
                    _tambah(v)
            elif isinstance(kec_map, (list, tuple, set)):
                for v in kec_map:
                    _tambah(v)
    except Exception:
        pass

    # 2. Dari hasil rekap jika sudah ada
    if hasil_rekap and isinstance(hasil_rekap, dict):
        for r in hasil_rekap.get("rekap", []):
            if r:
                _tambah(r[0])

    # 3. Jika masih kosong, coba ambil data master langsung dari siga_core
    if not kec_set:
        try:
            master_fresh = core.ambil_master(kab_id)
            if isinstance(master_fresh, dict):
                kec_map = master_fresh.get("kec")
                if isinstance(kec_map, dict):
                    for v in kec_map.values():
                        _tambah(v)
                elif isinstance(kec_map, (list, tuple, set)):
                    for v in kec_map:
                        _tambah(v)
                # Fallback jika struktur master menyimpan daftar/mapping poktan dengan nama kecamatan
                for key_alt in ("kecamatan", "daftar_kecamatan", "list_kec"):
                    val_alt = master_fresh.get(key_alt)
                    if isinstance(val_alt, dict):
                        for v in val_alt.values():
                            _tambah(v)
                    elif isinstance(val_alt, (list, tuple, set)):
                        for v in val_alt:
                            if isinstance(v, dict):
                                _tambah(v.get("nama") or v.get("nama_kec") or v.get("kec"))
                            else:
                                _tambah(v)
        except Exception:
            pass

    return sorted(kec_set)


def hitung_kebutuhan_persen_juara1(target_item: dict, semua_items: list, mode: str):
    """
    Menghitung peringkat berdasarkan PERSENTASE (bukan capaian mentah),
    lalu menghitung:
    - total capaian baru yang dibutuhkan = (capaian_sekarang + tambahan_capaian)
    - tambahan capaian yang harus dikejar agar (capaian_baru / target_kecamatan) * 100%
      melampaui persentase pemimpin (#1) saat ini.

    Struktur data r di rekap_rows siga_core:
      r[0] = Nama Kecamatan
      r[1] = Capaian BKB
      r[2] = Target BKB
      r[3] = % BKB
      r[4] = Target BKL
      r[5] = Capaian BKL
      r[6] = % BKL
    """
    if mode == "bkb":
        cap_key, tgt_key, pct_key, satuan = "bkb_cap", "bkb_tgt", "bkb_pct", "capaian BKB"
        label_indikator = "Persentase BKB (% BKB)"
    else:
        cap_key, tgt_key, pct_key, satuan = "bkl_cap", "bkl_tgt", "bkl_pct", "capaian BKL"
        label_indikator = "Persentase BKL (% BKL)"

    ranked = sorted(semua_items, key=lambda x: (x[pct_key], x[cap_key]), reverse=True)
    pos = next((idx + 1 for idx, x in enumerate(ranked) if x["kec"] == target_item["kec"]), len(ranked))
    leader = ranked[0] if ranked else target_item

    cap_now = target_item[cap_key]
    tgt_now = target_item[tgt_key]
    pct_now = target_item[pct_key]
    leader_pct = leader[pct_key]

    # Hitung persentase aktual dari (cap_now / tgt_now) jika target > 0
    if tgt_now > 0 and pct_now == 0.0 and cap_now > 0:
        pct_now = round((cap_now / tgt_now) * 100.0, 2)

    if pos == 1:
        runner_up_info = ""
        if len(ranked) > 1:
            ru = ranked[1]
            selisih = max(0.0, round(pct_now - ru[pct_key], 2))
            runner_up_info = f" (unggul {selisih:.2f}% atas #{2}: {ru['kec']} {ru[pct_key]:.2f}%)"
        return {
            "indikator": label_indikator,
            "pos": pos,
            "rank_str": "🏆 Peringkat 1",
            "leader": leader,
            "pct_now": pct_now,
            "leader_pct": leader_pct,
            "kurang_pct": 0.0,
            "tambahan_cap": 0,
            "total_cap_target": int(round(cap_now)),
            "pct_setelah_cap": pct_now,
            "satuan": satuan,
            "keterangan": f"Sudah Peringkat #1 (%){runner_up_info}",
        }

    # Persentase minimal yang harus dicapai agar melampaui pemimpin (#1)
    # Menggunakan kenaikan presisi 0.01% di atas persentase pemimpin saat ini
    pct_batas_salip = round(leader_pct + 0.01, 2)
    kurang_pct = max(0.01, round(pct_batas_salip - pct_now, 2))

    if tgt_now > 0:
        # Rumus: (total_capaian / tgt_now) * 100 >= pct_batas_salip
        # => total_capaian >= (pct_batas_salip / 100.0) * tgt_now
        total_cap_dibutuhkan = int(math.ceil(((pct_batas_salip / 100.0) * tgt_now) - 1e-9))
        tambahan_cap = max(1, total_cap_dibutuhkan - int(round(cap_now)))
        total_cap_baru = int(round(cap_now)) + tambahan_cap
        pct_baru = round((total_cap_baru / tgt_now) * 100.0, 2)

        # Pastikan persentase baru benar-benar > persentase leader
        while pct_baru <= leader_pct:
            tambahan_cap += 1
            total_cap_baru = int(round(cap_now)) + tambahan_cap
            pct_baru = round((total_cap_baru / tgt_now) * 100.0, 2)

        kurang_pct_aktual = max(0.0, round(pct_baru - pct_now, 2))
        ket = (
            f"Peringkat #{pos} (%). Butuh +{tambahan_cap:,} {satuan} "
            f"(total {total_cap_baru:,} / {int(round(tgt_now)):,} target = {pct_baru:.2f}%) "
            f"untuk salip {leader['kec']} ({leader_pct:.2f}%)"
        )
    else:
        tambahan_cap = 0
        total_cap_baru = int(round(cap_now))
        pct_baru = pct_now
        kurang_pct_aktual = max(0.0, round(pct_batas_salip - pct_now, 2))
        ket = f"Peringkat #{pos} (%). Target kecamatan 0, butuh +{kurang_pct_aktual:.2f}% salip {leader['kec']}"

    return {
        "indikator": label_indikator,
        "pos": pos,
        "rank_str": f"#{pos}",
        "leader": leader,
        "pct_now": pct_now,
        "leader_pct": leader_pct,
        "kurang_pct": kurang_pct_aktual,
        "tambahan_cap": tambahan_cap,
        "total_cap_target": total_cap_baru,
        "pct_setelah_cap": pct_baru,
        "satuan": satuan,
        "keterangan": ket,
    }


def hitung_analisis_target(rekap_rows, target_kec: str, kab_nama: str, bulan_nama: str, tahun_pilih: str):
    """
    Menghitung peringkat % BKB dan % BKL untuk target_kec di dalam kab_nama,
    serta kebutuhan capaian yang jika dibagi target kecamatan membuat persentasenya #1.
    """
    if not rekap_rows or not target_kec or target_kec == "(Tidak ada / Pantau semua)":
        return None

    parsed = []
    for r in rekap_rows:
        kec = str(r[0]).strip()
        bkb_cap = _angka_bersih(r[1])
        bkb_tgt = _angka_bersih(r[2])
        bkb_pct_raw = _angka_bersih(r[3])
        bkl_tgt = _angka_bersih(r[4])
        bkl_cap = _angka_bersih(r[5])
        bkl_pct_raw = _angka_bersih(r[6])

        bkb_pct = bkb_pct_raw if bkb_pct_raw > 0 or bkb_tgt == 0 else round((bkb_cap / bkb_tgt) * 100.0, 2)
        bkl_pct = bkl_pct_raw if bkl_pct_raw > 0 or bkl_tgt == 0 else round((bkl_cap / bkl_tgt) * 100.0, 2)

        parsed.append({
            "kec": kec,
            "bkb_cap": bkb_cap,
            "bkb_tgt": bkb_tgt,
            "bkb_pct": bkb_pct,
            "bkl_cap": bkl_cap,
            "bkl_tgt": bkl_tgt,
            "bkl_pct": bkl_pct,
        })

    target_item = next((x for x in parsed if x["kec"].upper() == target_kec.strip().upper()), None)
    if target_item is None:
        return None

    info_bkb = hitung_kebutuhan_persen_juara1(target_item, parsed, "bkb")
    info_bkl = hitung_kebutuhan_persen_juara1(target_item, parsed, "bkl")

    tabel_kejar = [
        [
            info_bkb["indikator"],
            target_item["kec"],
            info_bkb["rank_str"],
            f"{info_bkb['pct_now']:.2f}% ({int(round(target_item['bkb_cap'])):,}/{int(round(target_item['bkb_tgt'])):,})",
            f"{info_bkb['leader']['kec']} ({info_bkb['leader_pct']:.2f}%)",
            f"+{info_bkb['kurang_pct']:.2f}%",
            f"+{info_bkb['tambahan_cap']:,} (total {info_bkb['total_cap_target']:,} -> {info_bkb['pct_setelah_cap']:.2f}%)"
            if info_bkb["tambahan_cap"] > 0
            else "Sudah #1 (0 tambahan)",
            info_bkb["keterangan"],
        ],
        [
            info_bkl["indikator"],
            target_item["kec"],
            info_bkl["rank_str"],
            f"{info_bkl['pct_now']:.2f}% ({int(round(target_item['bkl_cap'])):,}/{int(round(target_item['bkl_tgt'])):,})",
            f"{info_bkl['leader']['kec']} ({info_bkl['leader_pct']:.2f}%)",
            f"+{info_bkl['kurang_pct']:.2f}%",
            f"+{info_bkl['tambahan_cap']:,} (total {info_bkl['total_cap_target']:,} -> {info_bkl['pct_setelah_cap']:.2f}%)"
            if info_bkl["tambahan_cap"] > 0
            else "Sudah #1 (0 tambahan)",
            info_bkl["keterangan"],
        ],
    ]

    return {
        "target_kec": target_item["kec"],
        "kab_nama": kab_nama,
        "periode": f"{bulan_nama} {tahun_pilih}",
        "pos_bkb": info_bkb["pos"],
        "pos_bkl": info_bkl["pos"],
        "leader_bkb": info_bkb["leader"],
        "leader_bkl": info_bkl["leader"],
        "target_item": target_item,
        "info_bkb": info_bkb,
        "info_bkl": info_bkl,
        "tabel_kejar": tabel_kejar,
    }


def cek_dan_kirim_notif_tersalip(worker, analisis, bot_token: str, chat_id: str):
    """
    Pantau transisi status: jika sebelumnya target berada di Peringkat 1 (posisi == 1)
    dan sekarang posisinya > 1 (tersalip), kirim notifikasi Telegram sekali per kejadian tersalip.
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
daftar_kec_aktif = ambil_daftar_kecamatan(kab_id_aktif, st.session_state.hasil_rekap)
opsi_kec.extend(daftar_kec_aktif)

if st.session_state.target_kec_pilih not in opsi_kec:
    opsi_kec.append(st.session_state.target_kec_pilih)

col_t1, col_t2 = st.columns([2.0, 3.0])
with col_t1:
    target_kec_pilih = st.selectbox(
        "Target Kecamatan Juara 1 (% BKB & % BKL)",
        options=opsi_kec,
        index=opsi_kec.index(st.session_state.target_kec_pilih),
        help="Pilih kecamatan untuk menyorot barisnya di seluruh tabel dan menghitung capaian yang harus dikejar agar persentasenya (#1) mengungguli kecamatan lain.",
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
        bkb_info = analisis["info_bkb"]
        bkl_info = analisis["info_bkl"]

        st.markdown(
            f"""
            <div class="target-banner">
                <strong>🎯 Target Highlight: {analisis['target_kec']}</strong> ({analisis['kab_nama']} — {analisis['periode']})<br/>
                • <b>% BKB</b>: Peringkat <b>#{bkb_info['pos']}</b> ({bkb_info['pct_now']:.2f}%) — Pemimpin: <b>{bkb_info['leader']['kec']}</b> ({bkb_info['leader_pct']:.2f}%)<br/>
                • <b>% BKL</b>: Peringkat <b>#{bkl_info['pos']}</b> ({bkl_info['pct_now']:.2f}%) — Pemimpin: <b>{bkl_info['leader']['kec']}</b> ({bkl_info['leader_pct']:.2f}%)
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.subheader(f"📈 Kebutuhan Capaian Mengejar Peringkat 1 (%) — {analisis['target_kec']}")
        st.caption(
            "Peringkat diukur berdasarkan **persentase (%)** masing-masing kecamatan. "
            "Tambahan capaian dihitung agar `(Capaian Baru / Target Kecamatan) × 100%` melampaui persentase pemimpin (#1)."
        )
        kol_kejar = [
            "Indikator (%)",
            "Kecamatan Target",
            "Peringkat %",
            "Persentase & Capaian Saat Ini",
            "Pemimpin #1 (%)",
            "Selisih % Kejar",
            "Capaian Harus Dikejar",
            "Rincian Perhitungan",
        ]
        df_kejar = pd.DataFrame(analisis["tabel_kejar"], columns=kol_kejar)
        st.dataframe(df_kejar, use_container_width=True, hide_index=True)

    def sorot_baris_rekap(row):
        nama_kec_row = str(row.get("Nama Kecamatan", "")).strip().upper()
        is_target = (
            bool(target_kec_aktif)
            and target_kec_aktif != "(Tidak ada / Pantau semua)"
            and nama_kec_row == target_kec_aktif.strip().upper()
        )

        try:
            persen_bkb = float(str(row["% BKB"]).replace("%", "").strip())
            di_atas_ambang = persen_bkb > core.AMBANG_BIRU
        except ValueError:
            di_atas_ambang = False

        styles = []
        for col_name in row.index:
            if is_target:
                styles.append(
                    "background-color: #FEF08A; color: #713F12; font-weight: 800; border-top: 2px solid #CA8A04; border-bottom: 2px solid #CA8A04;"
                )
            elif di_atas_ambang:
                styles.append("background-color: #0B5CAD; color: #FFFFFF; font-weight: 600;")
            else:
                styles.append("")
        return styles

    tab_rekap, tab_detail = st.tabs(["Rekap Kecamatan", "Detail Poktan"])

    with tab_rekap:
        ket_highlight = (
            "Seluruh kecamatan tetap ditampilkan. "
            f"Baris biru = % BKB di atas {core.AMBANG_BIRU:.0f}."
        )
        if analisis is not None:
            ket_highlight += f" Baris kuning tegas = kecamatan terpilih (**{analisis['target_kec']}**)."
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
'''

with open("app_web.py", "w", encoding="utf-8") as f:
    f.write(code_str)

compile(code_str, "app_web.py", "exec")
print("SUCCESS - app_web.py updated and verified!")
