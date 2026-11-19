# -*- coding: utf-8 -*-
"""
Logika inti SIGA BKKBN (tanpa tampilan). Dipakai bersama oleh:
  - main.py     -> versi Android (Kivy)
  - app_web.py  -> versi web (Streamlit)
Kebutuhan: Python 3 + paket `requests`.
"""

import csv
import io
import json
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================================================
# 1. KONFIGURASI
# ==================================================

BASE = "https://siga-api-gateway.bkkbn.go.id"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://siga.bkkbn.go.id/",
}
TIMEOUT = 15
WORKERS = 6            # permintaan paralel; turunkan (mis. 3) kalau server sering menolak / HP lemah
CACHE_DETIK = 3600

SHEET_URL = ("https://docs.google.com/spreadsheets/d/"
             "1dYLGLvdgRO_wOZjG6ycET3ai-WXpMBAO5V9ZvBFV3rI/export?format=csv&gid=0")
KOLOM_TARGET_BKB = "GAP_d3"
KOLOM_TARGET_BKL = "S4"
KOLOM_S_INDEX = 18
AMBANG_BIRU = 91.0

KEY_KEGIATAN = {"bkb": "kegiatanBkb", "bkl": "kegiatanBkl"}

KABUPATEN_MAPPING = {
    "LAMPUNG SELATAN": "124",
    "LAMPUNG TENGAH": "125",
    "LAMPUNG UTARA": "126",
    "LAMPUNG BARAT": "128",
    "TULANG BAWANG": "129",
    "TANGGAMUS": "130",
    "LAMPUNG TIMUR": "132",
    "WAY KANAN": "133",
    "PESAWARAN": "134",
    "PRINGSEWU": "135",
    "MESUJI": "136",
    "TULANG BAWANG BARAT": "137",
    "PESISIR BARAT": "500",
    "KOTA BANDAR LAMPUNG": "127",
    "KOTA METRO": "131",
}

BULAN = {
    "Januari (1)": 1, "Februari (2)": 2, "Maret (3)": 3, "April (4)": 4,
    "Mei (5)": 5, "Juni (6)": 6, "Juli (7)": 7, "Agustus (8)": 8,
    "September (9)": 9, "Oktober (10)": 10, "November (11)": 11, "Desember (12)": 12,
}
TAHUN = ["2024", "2025", "2026", "2027", "2028"]

KOLOM_REKAP = ["Nama Kecamatan", "Total Peserta Riil", "Target BKB", "% BKB",
               "Target BKL", "Capaian BKL", "% BKL"]
KOLOM_DETAIL = ["Jenis", "Nama Kecamatan", "ID Poktan", "Nama Poktan",
                "Jumlah (BKB: Peserta Riil / BKL: nomorBKL Unik)", "Status API"]

# ==================================================
# 2. HELPER HTTP & JSON
# ==================================================

_local = threading.local()


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update(HEADERS)
        s.verify = False
        _local.s = s
    return s


def parse_json(x):
    """Buka string JSON yang bersarang (API sering mengirim JSON di dalam string)."""
    for _ in range(3):
        if not isinstance(x, str):
            break
        s = x.strip()
        if not s or s[0] not in '[{"':
            break
        try:
            x = json.loads(s)
        except ValueError:
            break
    return x


def get_json(url):
    """GET + parse. Mencoba 2x; melempar exception bila tetap gagal."""
    galat = None
    for _ in range(2):
        try:
            r = _session().get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                return parse_json(r.text)
            galat = RuntimeError(f"HTTP {r.status_code}")
            if r.status_code < 500:
                break
        except requests.RequestException as e:
            galat = e
        time.sleep(0.5)
    raise galat


def unwrap(d, key):
    if isinstance(d, dict):
        kecil = key.lower()
        for k, v in d.items():
            if str(k).lower() == kecil:
                return v
    return None


def _ke_list(data):
    data = parse_json(data)
    if isinstance(data, dict):
        for v in data.values():
            v = parse_json(v)
            if isinstance(v, list):
                data = v
                break
    if not isinstance(data, list):
        return []
    return [d for d in (parse_json(x) for x in data) if isinstance(d, dict)]


def _ke_int(x):
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


def to_num(v):
    s = str(v).strip().replace(" ", "").replace("%", "")
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


# ==================================================
# 3. API SIGA
# ==================================================

def get_poktan(kab_id, jenis):
    url = (f"{BASE}/poktan/siga/poktan/getListPoktan?filterPencarian="
           f"%7B%22provinsiId%22%3A%228%22%2C%22kabupatenId%22%3A%22{kab_id}%22"
           f"%2C%22kecamatanId%22%3A%220%22%2C%22kelurahanId%22%3A%220%22"
           f"%2C%22rwId%22%3A%220%22%2C%22rtId%22%3A%220%22%7D&jenisPoktan={jenis}")
    return _ke_list(get_json(url))


def get_kecamatan_mapping(kab_id):
    url = f"{BASE}/location-service/siga/location/getListKecamatanByIdKabupaten?id_kabupaten={kab_id}"
    mapping = {}
    for item in _ke_list(get_json(url)):
        k_id = (item.get("id") or item.get("kecamatanId")
                or item.get("kodeKecamatan") or item.get("id_kecamatan"))
        k_nama = item.get("nama_kecamatan") or item.get("nama")
        if k_id is not None and k_nama is not None:
            mapping[str(k_id).strip()] = str(k_nama).strip().upper()
    return mapping


_MASTER = {}
_MASTER_LOCK = threading.Lock()


def ambil_master(kab_id, paksa=False):
    """Daftar poktan BKB, poktan BKL, dan peta kecamatan (di-cache)."""
    with _MASTER_LOCK:
        c = _MASTER.get(kab_id)
        if c and not paksa and time.time() - c["waktu"] < CACHE_DETIK:
            return c

    catatan = []

    def aman(fungsi, *args, nama, default):
        try:
            return fungsi(*args)
        except Exception as e:
            catatan.append(f"Gagal ambil {nama}: {e}")
            return default

    with ThreadPoolExecutor(max_workers=3) as ex:
        f_bkb = ex.submit(aman, get_poktan, kab_id, "bkb", nama="poktan BKB", default=[])
        f_bkl = ex.submit(aman, get_poktan, kab_id, "bkl", nama="poktan BKL", default=[])
        f_kec = ex.submit(aman, get_kecamatan_mapping, kab_id, nama="data kecamatan", default={})
        hasil = {"bkb": f_bkb.result(), "bkl": f_bkl.result(),
                 "kec": f_kec.result(), "catatan": catatan, "waktu": time.time()}

    if hasil["bkb"] or hasil["bkl"]:
        with _MASTER_LOCK:
            _MASTER[kab_id] = hasil
    return hasil


def get_sheet():
    """Unduh spreadsheet target sebagai (header, baris)."""
    res = requests.get(SHEET_URL, headers=HEADERS, verify=False, timeout=TIMEOUT,
                       allow_redirects=True)
    if res.status_code != 200:
        raise RuntimeError(f"Google Sheet HTTP {res.status_code}")
    res.encoding = "utf-8"
    teks = res.text
    awal = teks.lstrip().lower()
    if awal.startswith("<!doctype html") or awal.startswith("<html") or "accounts.google.com" in awal:
        raise RuntimeError("Google Sheet belum bisa diakses. Ubah akses menjadi "
                           "'Anyone with the link -> Viewer' atau cek gid sheet.")
    baris = list(csv.reader(io.StringIO(teks)))
    if len(baris) < 2:
        raise RuntimeError("Google Sheet berhasil diakses tetapi tidak berisi data.")
    return [h.strip() for h in baris[0]], baris[1:]


def _sel(row, idx):
    return row[idx] if idx is not None and idx < len(row) else ""


def siapkan_target(sheet):
    """Kembalikan (target_bkb, target_bkl, catatan)."""
    catatan = []
    if sheet is None:
        pesan = "Gagal Ambil Google Sheet"
        return pesan, pesan, catatan

    headers, rows = sheet
    kec_idx = next((i for i, h in enumerate(headers) if "kecamatan" in h.lower()), None)
    bkb_idx = next((i for i, h in enumerate(headers)
                    if h.lower() == KOLOM_TARGET_BKB.lower()), None)
    bkl_idx = next((i for i, h in enumerate(headers)
                    if h.upper() == KOLOM_TARGET_BKL.upper()), None)
    if bkl_idx is None and len(headers) > KOLOM_S_INDEX:
        bkl_idx = KOLOM_S_INDEX
        catatan.append(f"Header '{KOLOM_TARGET_BKL}' tidak ditemukan; Target BKL diambil dari "
                       f"kolom S (header: '{headers[bkl_idx]}').")

    def bangun(idx):
        if kec_idx is None or idx is None:
            return "Struktur Kolom Salah"
        out = {}
        for r in rows:
            kec = _sel(r, kec_idx).strip().upper()
            if kec:
                out[kec] = to_num(_sel(r, idx))
        return out

    return bangun(bkb_idx), bangun(bkl_idx), catatan


# ==================================================
# 4. PARSING KEGIATAN & PERHITUNGAN
# ==================================================

def _cari_list_dict(obj):
    obj = parse_json(obj)
    if isinstance(obj, list) and obj and isinstance(parse_json(obj[0]), dict):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            r = _cari_list_dict(v)
            if r:
                return r
    return None


def extract_kegiatan(raw, jenis):
    key = KEY_KEGIATAN[jenis]
    raw = parse_json(raw)
    items = []
    if isinstance(raw, dict):
        inner = parse_json(unwrap(raw, key))
        if isinstance(inner, list):
            items = [parse_json(i) for i in inner]
        elif isinstance(inner, dict):
            items = [inner]
    elif isinstance(raw, list):
        for x in raw:
            x = parse_json(x)
            if not isinstance(x, dict):
                continue
            kb = unwrap(x, key)
            if kb is not None:
                kb = parse_json(kb)
                if isinstance(kb, dict):
                    items.append(kb)
            else:
                items.append(x)
    return [i for i in items if isinstance(i, dict)]


def get_detail(pid, tgl, jenis):
    url = (f"{BASE}/poktan/siga/poktan/getDetailPoktanKegiatan"
           f"?id={pid}&tanggalKegiatan={tgl}&jenisPoktan={jenis}")
    d = get_json(url)
    kb = unwrap(d, KEY_KEGIATAN[jenis])
    return parse_json(kb) if kb is not None else d


def _tahun_dari_tanggal(tgl):
    s = str(tgl or "").strip()
    for sep in "-/.":
        if sep in s:
            return s.split(sep)[-1].strip()
    return ""


def cocok_periode(kb, bulan, tahun):
    tgl = str(kb.get("tanggalKegiatan", "") or "").strip()
    bulan_ok = _ke_int(kb.get("bulan")) == bulan
    for sep in "-/.":
        if sep in tgl:
            bagian = tgl.split(sep)
            if len(bagian) >= 3 and _ke_int(bagian[1]) == bulan:
                bulan_ok = True
            break
    return bulan_ok and str(tahun) in tgl


def ekstrak_nomor_bkl(detail):
    peserta = parse_json(unwrap(detail, "pesertaKegiatan"))
    if not isinstance(peserta, list):
        peserta = _cari_list_dict(detail) or []
    hasil = []
    for p in peserta:
        p = parse_json(p)
        if not isinstance(p, dict):
            continue
        val = unwrap(p, "nomorBKL")
        if val is not None:
            no_bkl = str(val).strip().upper()
            if no_bkl and no_bkl != "NONE" and no_bkl != "NULL":
                hasil.append(no_bkl)
    return hasil


def proses_poktan(pid, jenis, bulan, tahun):
    """Data satu poktan untuk bulan/tahun terpilih."""
    h = {"nama": [], "lansia": [], "status": ""}
    try:
        raw = get_json(f"{BASE}/poktan/siga/poktan/getListPoktanKegiatan?id={pid}&jenisPoktan={jenis}")
        items = extract_kegiatan(raw, jenis)
        if not items:
            h["status"] = "Tidak ada array kegiatan di dalam JSON"
            return h

        periode_ada, cocok, diproses = [], 0, 0
        for kb in items:
            bln_api = kb.get("bulan")
            tgl = kb.get("tanggalKegiatan", "")
            if bln_api is not None:
                periode_ada.append(f"{bln_api}-{_tahun_dari_tanggal(tgl) or '?'}")
            if not cocok_periode(kb, bulan, tahun):
                continue
            cocok += 1
            detail = get_detail(pid, tgl, jenis)
            if jenis == "bkb":
                peserta = parse_json(unwrap(detail, "pesertaKegiatan"))
                if isinstance(peserta, list) and peserta:
                    for p in peserta:
                        if isinstance(p, dict) and p.get("nama"):
                            nama = str(p["nama"]).strip().upper()
                            if nama:
                                h["nama"].append(nama)
                    diproses += 1
            else:
                h["lansia"].extend(ekstrak_nomor_bkl(detail))
                diproses += 1

        if not cocok:
            ada = ", ".join(sorted(set(periode_ada))) or "Kosong"
            h["status"] = f"Zonk (Di API adanya: {ada})"
        elif not diproses:
            h["status"] = "Peserta Kosong (0)"
        elif jenis == "bkl" and len(set(h["lansia"])) == 0:
            h["status"] = f"Tidak ada nomorBKL (0) di {diproses} Kegiatan"
        else:
            h["status"] = f"Sukses ({diproses} Kegiatan)"
    except Exception as e:
        h["status"] = f"Error: {e}"
    return h


def hitung_persen(capaian, target):
    if isinstance(target, (int, float)) and target > 0:
        return round(capaian / target * 100, 2)
    return 0.0


def jalankan_rekap(kab_id, bulan, tahun, lapor):
    """Rekap BKB + BKL per kecamatan. `lapor(selesai, total, teks)` dipanggil
    dari thread yang memanggil fungsi ini (bukan dari thread pekerja)."""
    lapor(0, 1, "Mengambil master kelompok, kecamatan & target...")
    catatan = []
    master = ambil_master(kab_id)
    catatan += master["catatan"]
    bkb, bkl, kec_map = master["bkb"], master["bkl"], master["kec"]
    if not bkb and not bkl:
        raise RuntimeError("Gagal terhubung ke server BKKBN untuk wilayah ini. "
                           "Pastikan API aktif.\n" + "\n".join(master["catatan"]))

    try:
        sheet = get_sheet()
    except Exception as e:
        sheet = None
        catatan.append(str(e))
    target_bkb, target_bkl, cat_sheet = siapkan_target(sheet)
    catatan += cat_sheet

    jobs = [("bkb", p) for p in bkb] + [("bkl", p) for p in bkl]
    total = len(jobs)
    hasil = [None] * total

    def kerja(i):
        jenis, p = jobs[i]
        return i, proses_poktan(p.get("id"), jenis, bulan, tahun)

    selesai = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for fut in as_completed([ex.submit(kerja, i) for i in range(total)]):
            i, h = fut.result()
            hasil[i] = h
            selesai += 1
            jenis, p = jobs[i]
            lapor(selesai, total,
                  f"Memproses [{selesai}/{total}] {jenis.upper()}: {p.get('namaKelompok', 'Tanpa Nama')}")

    peserta_kec = defaultdict(int)
    lansia_kec = defaultdict(int)
    kec_urutan = []
    seen_kec = set()
    detail_rows = []
    for (jenis, p), h in zip(jobs, hasil):
        kec_id = str(p.get("kecamatanId", "")).strip()
        kec = kec_map.get(kec_id, f"Kecamatan {kec_id}")
        if kec not in seen_kec:
            seen_kec.add(kec)
            kec_urutan.append(kec)
        if jenis == "bkb":
            jumlah = len(set(h["nama"]))
            peserta_kec[kec] += jumlah
        else:
            jumlah = len(set(h["lansia"]))
            lansia_kec[kec] += jumlah
        detail_rows.append([jenis.upper(), kec, p.get("id"),
                            p.get("namaKelompok", "Tanpa Nama"), jumlah, h["status"]])

    rekap_rows = []
    for kec in kec_urutan:
        peserta = peserta_kec.get(kec, 0)
        capaian = lansia_kec.get(kec, 0)
        tb = target_bkb.get(kec, 0.0) if isinstance(target_bkb, dict) else target_bkb
        tl = target_bkl.get(kec, 0.0) if isinstance(target_bkl, dict) else target_bkl
        rekap_rows.append([kec, peserta, tb, hitung_persen(peserta, tb),
                           tl, capaian, hitung_persen(capaian, tl)])

    return {"rekap": rekap_rows, "detail": detail_rows, "catatan": catatan}


# ==================================================
# 5. FORMAT
# ==================================================

def fmt_angka(v):
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:.2f}"
    return "" if v is None else v


def fmt_persen(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else v
