# -*- coding: utf-8 -*-
"""
SIGA BKKBN Data Explorer - versi Android (Kivy), tema biru-putih.
File ini harus bernama main.py (syarat buildozer) dan satu folder dengan siga_core.py.

Coba di PC dulu:  pip install kivy requests   lalu   python main.py
"""

import csv
import os
import threading
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex as hexc

import siga_core as core

# ---------- warna ----------
BIRU, BIRU_TUA, BIRU_MUDA = "#0B5CAD", "#073B73", "#E3EEFA"
LATAR, PUTIH, TEKS, ABU, GARIS = "#F4F8FD", "#FFFFFF", "#12263F", "#5B6B7F", "#C9D8EA"
ZEBRA, KUNING_BG, KUNING_FG = "#F8FBFE", "#FFF1D6", "#6B4300"

TINGGI_BARIS = dp(42)

KOL_REKAP = ["No", "Nama Kecamatan", "Total Peserta Riil", "Target BKB", "% BKB",
             "Target BKL", "Capaian BKL", "% BKL"]
LEBAR_REKAP = [32, 150, 72, 64, 64, 64, 72, 64]
KOL_DETAIL = ["No", "Jenis", "Kecamatan", "ID Poktan", "Nama Poktan", "Jumlah", "Status API"]
LEBAR_DETAIL = [32, 54, 130, 66, 130, 66, 212]


def _nilai_sort(v):
    s = str(v).strip().replace(",", "").replace("%", "")
    try:
        return (0, float(s))
    except ValueError:
        return (1, str(v).lower())


# ---------- komponen tampilan ----------
class Kotak(BoxLayout):
    """BoxLayout berlatar warna, sudut membulat, garis tepi opsional."""

    def __init__(self, warna=PUTIH, radius=12, garis=None, **kw):
        super().__init__(**kw)
        self._r = dp(radius)
        with self.canvas.before:
            Color(*hexc(warna))
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[self._r])
            self._ln = None
            if garis:
                Color(*hexc(garis))
                self._ln = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, self._r),
                                width=1)
        self.bind(pos=self._ubah, size=self._ubah)

    def _ubah(self, *a):
        self._bg.pos, self._bg.size = self.pos, self.size
        if self._ln is not None:
            self._ln.rounded_rectangle = (self.x, self.y, self.width, self.height, self._r)


class Btn(Button):
    def __init__(self, bg=BIRU, fg=PUTIH, garis=None, radius=10, **kw):
        super().__init__(background_normal="", background_down="", background_color=(0, 0, 0, 0),
                         color=hexc(fg), bold=True, **kw)
        self._r = dp(radius)
        with self.canvas.before:
            self._c = Color(*hexc(bg))
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[self._r])
            self._ln = None
            if garis:
                Color(*hexc(garis))
                self._ln = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, self._r),
                                width=dp(1.3))
        self.bind(pos=self._ubah, size=self._ubah, disabled=self._cek)

    def _ubah(self, *a):
        self._bg.pos, self._bg.size = self.pos, self.size
        if self._ln is not None:
            self._ln.rounded_rectangle = (self.x, self.y, self.width, self.height, self._r)

    def _cek(self, *a):
        self._c.a = 0.5 if self.disabled else 1

    def warna(self, bg, fg):
        self._c.rgba = hexc(bg)
        self.color = hexc(fg)


class Opsi(SpinnerOption):
    def __init__(self, **kw):
        super().__init__(background_normal="", background_down="", background_color=hexc(PUTIH),
                         color=hexc(TEKS), **kw)


class Pilih(Spinner):
    def __init__(self, **kw):
        super().__init__(background_normal="", background_down="", background_color=(0, 0, 0, 0),
                         color=hexc(TEKS), option_cls=Opsi, size_hint_y=None, height=dp(44),
                         halign="left", valign="middle", font_size=dp(14), **kw)
        with self.canvas.before:
            Color(*hexc(PUTIH))
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
            Color(*hexc(GARIS))
            self._ln = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(10)), width=1)
        self.bind(pos=self._ubah, size=self._ubah)

    def _ubah(self, *a):
        self._bg.pos, self._bg.size = self.pos, self.size
        self._ln.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(10))
        self.text_size = (self.width - dp(24), self.height)


class Bar(Widget):
    nilai = NumericProperty(0)  # 0..1

    def __init__(self, **kw):
        super().__init__(size_hint_y=None, height=dp(8), **kw)
        self.bind(pos=self._gambar, size=self._gambar, nilai=self._gambar)

    def _gambar(self, *a):
        self.canvas.clear()
        with self.canvas:
            Color(*hexc(BIRU_MUDA))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(4)])
            Color(*hexc(BIRU))
            RoundedRectangle(pos=self.pos, size=(self.width * max(0, min(1, self.nilai)), self.height),
                             radius=[dp(4)])


def teks_kecil(teks, tinggi=16, ukuran=12, warna=ABU, bold=False):
    lb = Label(text=teks, color=hexc(warna), font_size=dp(ukuran), bold=bold, halign="left",
               valign="middle", size_hint_y=None, height=dp(tinggi))
    lb.bind(size=lambda w, s: setattr(w, "text_size", (s[0], s[1])))
    return lb


class Cell(Label):
    def __init__(self, bg, fg, kiri, lebar, **kw):
        super().__init__(color=hexc(fg), font_size=dp(12), max_lines=2,
                         halign="left" if kiri else "center", valign="middle", **kw)
        self.text_size = (dp(lebar) - dp(8), TINGGI_BARIS)
        with self.canvas.before:
            Color(*hexc(bg))
            self._r = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._ubah, size=self._ubah)

    def _ubah(self, *a):
        self._r.pos, self._r.size = self.pos, self.size


class Table(ScrollView):
    """Tabel yang bisa digeser; ketuk judul kolom untuk mengurutkan."""

    def __init__(self, **kw):
        super().__init__(do_scroll_x=True, do_scroll_y=True, bar_width=dp(5), **kw)
        self.cols, self.items, self.widths, self.kiri, self.status_col = [], [], [], set(), None
        self.urut_kol, self.naik = None, True
        self.grid = GridLayout(size_hint=(None, None), spacing=dp(1),
                               row_default_height=TINGGI_BARIS, row_force_default=True)
        self.grid.bind(minimum_height=self.grid.setter("height"))
        self.add_widget(self.grid)

    def set_data(self, cols, rows, widths, kiri=(), sorot=None, status_col=None):
        """rows: list of list; sorot: list bool (baris biru) sepanjang rows."""
        self.cols, self.widths, self.kiri, self.status_col = cols, widths, set(kiri), status_col
        sorot = sorot or [False] * len(rows)
        self.items = [(list(r), s) for r, s in zip(rows, sorot)]
        self.urut_kol, self.naik = None, True
        self._gambar()

    def _urutkan(self, idx):
        self.naik = (not self.naik) if self.urut_kol == idx else True
        self.urut_kol = idx
        self.items.sort(key=lambda it: _nilai_sort(it[0][idx]), reverse=not self.naik)
        self._gambar()

    def _gambar(self):
        g = self.grid
        g.clear_widgets()
        g.cols = len(self.cols)
        g.cols_minimum = {i: dp(w) for i, w in enumerate(self.widths)}
        g.width = dp(sum(self.widths)) + dp(len(self.cols))
        for i, c in enumerate(self.cols):
            panah = (" ▲" if self.naik else " ▼") if self.urut_kol == i else ""
            b = Btn(bg=BIRU_MUDA, fg=BIRU_TUA, radius=0, text=c + panah, font_size=dp(11),
                    halign="center", valign="middle")
            b.text_size = (dp(self.widths[i]) - dp(6), TINGGI_BARIS)
            b.bind(on_release=lambda _b, i=i: self._urutkan(i))
            g.add_widget(b)
        for n, (row, sorot) in enumerate(self.items):
            bg_baris, fg_baris = (BIRU, PUTIH) if sorot else ((ZEBRA if n % 2 else PUTIH), TEKS)
            for j, v in enumerate(row):
                bg, fg = bg_baris, fg_baris
                if j == self.status_col and not str(v).startswith("Sukses"):
                    bg, fg = KUNING_BG, KUNING_FG
                g.add_widget(Cell(bg, fg, j in self.kiri, self.widths[j], text=str(v)))


# ---------- aplikasi ----------
class SigaApp(App):
    title = "SIGA BKKBN"

    def build(self):
        Window.clearcolor = hexc(LATAR)
        self.rekap_rows, self.detail_rows, self.periode = [], [], ""
        self.sibuk = False

        luar = BoxLayout(orientation="vertical")

        # header
        head = Kotak(warna=BIRU, radius=0, size_hint_y=None, height=dp(72),
                     padding=[dp(16), dp(10)], spacing=dp(12))
        logo = Kotak(warna=PUTIH, radius=12, size_hint=(None, None), size=(dp(44), dp(44)))
        logo.add_widget(Label(text="S", bold=True, font_size=dp(22), color=hexc(BIRU)))
        head.add_widget(logo)
        judul = BoxLayout(orientation="vertical")
        judul.add_widget(teks_kecil("SIGA BKKBN", tinggi=26, ukuran=18, warna=PUTIH, bold=True))
        judul.add_widget(teks_kecil("Rekap BKB & BKL per kecamatan", tinggi=18, ukuran=12, warna="#D6E6F8"))
        head.add_widget(judul)
        luar.add_widget(head)

        # isi (bisa digulir ke bawah)
        isi = ScrollView(do_scroll_x=False, bar_width=dp(4))
        kol = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(12),
                        padding=[dp(14), dp(14), dp(14), dp(16)])
        kol.bind(minimum_height=kol.setter("height"))
        isi.add_widget(kol)
        luar.add_widget(isi)

        # kartu filter
        kartu = Kotak(PUTIH, 16, GARIS, orientation="vertical", size_hint_y=None,
                      padding=dp(14), spacing=dp(8))
        kartu.bind(minimum_height=kartu.setter("height"))
        kartu.add_widget(teks_kecil("Kabupaten/Kota"))
        self.sp_kab = Pilih(text="KOTA BANDAR LAMPUNG", values=list(core.KABUPATEN_MAPPING))
        kartu.add_widget(self.sp_kab)

        sekarang = datetime.now()
        nama_bulan = next(k for k, v in core.BULAN.items() if v == sekarang.month)
        tahun = str(sekarang.year) if str(sekarang.year) in core.TAHUN else "2026"
        baris = BoxLayout(size_hint_y=None, height=dp(66), spacing=dp(10))
        kb = BoxLayout(orientation="vertical", spacing=dp(4))
        kb.add_widget(teks_kecil("Bulan"))
        self.sp_bulan = Pilih(text=nama_bulan, values=list(core.BULAN))
        kb.add_widget(self.sp_bulan)
        kt = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_x=None, width=dp(104))
        kt.add_widget(teks_kecil("Tahun"))
        self.sp_tahun = Pilih(text=tahun, values=core.TAHUN)
        kt.add_widget(self.sp_tahun)
        baris.add_widget(kb)
        baris.add_widget(kt)
        kartu.add_widget(baris)

        self.btn_run = Btn(text="Jalankan Rekap", font_size=dp(15), size_hint_y=None,
                           height=dp(48), radius=12)
        self.btn_run.bind(on_release=lambda *a: self.mulai())
        kartu.add_widget(self.btn_run)

        csv_baris = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))
        b1 = Btn(bg=PUTIH, fg=BIRU, garis=BIRU, text="CSV Rekap", font_size=dp(13))
        b1.bind(on_release=lambda *a: self.simpan_csv(
            core.KOLOM_REKAP, self.rekap_rows, f"rekap_siga_{self.periode}.csv"))
        b2 = Btn(bg=PUTIH, fg=BIRU, garis=BIRU, text="CSV Detail", font_size=dp(13))
        b2.bind(on_release=lambda *a: self.simpan_csv(
            core.KOLOM_DETAIL, self.detail_rows, f"detail_siga_{self.periode}.csv"))
        csv_baris.add_widget(b1)
        csv_baris.add_widget(b2)
        kartu.add_widget(csv_baris)
        kol.add_widget(kartu)

        # kartu progres
        prog = Kotak(PUTIH, 12, GARIS, orientation="vertical", size_hint_y=None, height=dp(74),
                     padding=[dp(14), dp(10)], spacing=dp(6))
        self.lbl = Label(text="Siap.", color=hexc(TEKS), font_size=dp(12), halign="left",
                         valign="middle")
        self.lbl.bind(size=lambda w, s: setattr(w, "text_size", (s[0], s[1])))
        self.bar = Bar()
        prog.add_widget(self.lbl)
        prog.add_widget(self.bar)
        kol.add_widget(prog)

        # tab (rekap / detail)
        tab = Kotak(BIRU_MUDA, 12, size_hint_y=None, height=dp(44), padding=dp(4), spacing=dp(4))
        self.btn_tab = [Btn(text="Rekap Kecamatan", font_size=dp(13), radius=9),
                        Btn(text="Detail Poktan", font_size=dp(13), radius=9)]
        for i, b in enumerate(self.btn_tab):
            b.bind(on_release=lambda _b, i=i: self.pilih_tab(i))
            tab.add_widget(b)
        kol.add_widget(tab)

        # tabel
        self.area = Kotak(PUTIH, 12, GARIS, size_hint_y=None, height=dp(440), padding=dp(1))
        self.tbl1, self.tbl2 = Table(), Table()
        self.tbl1.set_data(KOL_REKAP, [], LEBAR_REKAP, kiri={1})
        self.tbl2.set_data(KOL_DETAIL, [], LEBAR_DETAIL, kiri={2, 4, 6}, status_col=6)
        kol.add_widget(self.area)
        kol.add_widget(teks_kecil("Baris biru = % BKB di atas 91. Ketuk judul kolom untuk mengurutkan.",
                                  tinggi=32, ukuran=11))
        self.pilih_tab(0)
        return luar

    # ---------- util ----------
    def pilih_tab(self, i):
        for n, b in enumerate(self.btn_tab):
            b.warna(BIRU, PUTIH) if n == i else b.warna(BIRU_MUDA, BIRU_TUA)
        self.area.clear_widgets()
        self.area.add_widget(self.tbl1 if i == 0 else self.tbl2)

    def popup(self, judul, teks):
        isi = Label(text=teks, halign="left", valign="middle")
        isi.bind(size=lambda w, s: setattr(w, "text_size", (s[0] - dp(10), None)))
        Popup(title=judul, content=isi, size_hint=(0.9, 0.5)).open()

    def folder_simpan(self):
        try:  # Android: folder file aplikasi (tanpa izin tambahan)
            from jnius import autoclass
            aktivitas = autoclass("org.kivy.android.PythonActivity").mActivity
            d = aktivitas.getExternalFilesDir(None)
            if d is not None:
                return d.getAbsolutePath()
        except Exception:
            pass
        return self.user_data_dir

    def simpan_csv(self, header, rows, nama):
        if not rows:
            self.popup("Simpan CSV", "Belum ada data untuk disimpan.")
            return
        try:
            path = os.path.join(self.folder_simpan(), nama)
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(rows)
            self.popup("Tersimpan", f"File disimpan di:\n{path}")
        except Exception as e:
            self.popup("Gagal menyimpan", str(e))

    # ---------- rekap ----------
    def mulai(self):
        if self.sibuk:
            return
        kab = core.KABUPATEN_MAPPING[self.sp_kab.text]
        bulan = core.BULAN[self.sp_bulan.text]
        tahun = self.sp_tahun.text
        self.sibuk = True
        self.btn_run.disabled = True
        self.bar.nilai = 0
        self.periode = f"{kab}_{bulan}_{tahun}"

        def lapor(d, t, txt):
            Clock.schedule_once(lambda dt: self._progres(d, t, txt))

        def kerja():
            try:
                hasil = core.jalankan_rekap(kab, bulan, tahun, lapor)
                Clock.schedule_once(lambda dt: self._selesai(hasil))
            except Exception as e:
                pesan = str(e)
                Clock.schedule_once(lambda dt: self._gagal(pesan))

        threading.Thread(target=kerja, daemon=True).start()

    def _progres(self, d, t, txt):
        self.bar.nilai = d / max(t, 1)
        self.lbl.text = txt

    def _gagal(self, pesan):
        self.sibuk = False
        self.btn_run.disabled = False
        self.lbl.text = "Gagal."
        self.popup("Gagal", pesan)

    def _selesai(self, hasil):
        self.sibuk = False
        self.btn_run.disabled = False
        self.bar.nilai = 1
        self.rekap_rows, self.detail_rows = hasil["rekap"], hasil["detail"]

        rows, sorot = [], []
        for i, r in enumerate(self.rekap_rows, 1):
            rows.append([i, r[0], core.fmt_angka(r[1]), core.fmt_angka(r[2]), core.fmt_persen(r[3]),
                         core.fmt_angka(r[4]), core.fmt_angka(r[5]), core.fmt_persen(r[6])])
            sorot.append(isinstance(r[3], (int, float)) and r[3] > core.AMBANG_BIRU)
        self.tbl1.set_data(KOL_REKAP, rows, LEBAR_REKAP, kiri={1}, sorot=sorot)

        drows = [[i] + r for i, r in enumerate(self.detail_rows, 1)]
        self.tbl2.set_data(KOL_DETAIL, drows, LEBAR_DETAIL, kiri={2, 4, 6}, status_col=6)

        ket = " | ".join(hasil["catatan"])
        self.lbl.text = "Selesai memproses seluruh poktan." + (f" Catatan: {ket}" if ket else "")


if __name__ == "__main__":
    SigaApp().run()
