import customtkinter as ctk
import threading
import time
import os
import subprocess
import sys
import multiprocessing
import re 
import pandas as pd
from tkinter import filedialog

from blibli_scraper import scrape_blibli
from tokopedia_scraper import scrape_tokopedia 
from shopee_scraper import scrape_shopee 

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

class MultiScraperApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Geo-Scraper E-Commerce Pro v2.5 (Bulk Edition)")
        self.geometry("950x700")
        self.minsize(850, 600)

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.stop_flag = False
        self.bulk_filepath = None
        self.saved_keywords = [] # Untuk menyimpan keyword dari Excel
        
        self.timer_running = False
        self.start_time_ui = None

        # ================= FRAME HEADER & LOKASI GLOBAL =================
        self.frame_header = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_header.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="ew")
        
        self.label_title = ctk.CTkLabel(self.frame_header, text="E-Commerce Geo-Scraper v2.5", font=ctk.CTkFont(size=24, weight="bold"), text_color="#1F538D")
        self.label_title.pack()
        self.label_subtitle = ctk.CTkLabel(self.frame_header, text="Mode Pencarian Massal & Pemetaan Spasial", text_color="gray")
        self.label_subtitle.pack(pady=(0, 10))

        # FITUR BARU: Filter Lokasi Dinamis
        self.frame_lokasi = ctk.CTkFrame(self.frame_header, fg_color="transparent")
        self.frame_lokasi.pack()
        self.label_lokasi = ctk.CTkLabel(self.frame_lokasi, text="📍 Target Lokasi:", font=ctk.CTkFont(weight="bold"))
        self.label_lokasi.pack(side="left", padx=5)
        
        # Pengguna bisa memilih dari list atau mengetik kota manual
        list_kota = ["Kab. Bantul", "Kota Yogyakarta", "Kab. Sleman", "Kota Jakarta Selatan", "Kota Bandung", "Kota Surabaya", "Kota Semarang", "Kota Medan", "Kota Makassar"]
        self.combo_lokasi = ctk.CTkComboBox(self.frame_lokasi, values=list_kota, width=220)
        self.combo_lokasi.set("Kab. Bantul")
        self.combo_lokasi.pack(side="left", padx=5)

        # ================= TABS (SINGLE & BULK) =================
        self.tabview = ctk.CTkTabview(self, height=120)
        self.tabview.grid(row=1, column=0, padx=20, pady=(5, 10), sticky="ew")
        
        self.tab_single = self.tabview.add("Pencarian Tunggal (Single)")
        self.tab_bulk = self.tabview.add("Pencarian Massal (Upload Excel)")

        # --- ISI TAB SINGLE ---
        self.tab_single.grid_columnconfigure((0,1,2,3,4), weight=1)
        
        self.label_keyword = ctk.CTkLabel(self.tab_single, text="Kata Kunci:", font=ctk.CTkFont(weight="bold"))
        self.label_keyword.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="e")

        self.entry_keyword = ctk.CTkEntry(self.tab_single, placeholder_text="Contoh: Semen", width=180)
        self.entry_keyword.insert(0, "Semen")
        self.entry_keyword.grid(row=0, column=1, padx=5, pady=10, sticky="w")

        self.label_sumber = ctk.CTkLabel(self.tab_single, text="Sumber:", font=ctk.CTkFont(weight="bold"))
        self.label_sumber.grid(row=0, column=2, padx=(10, 5), pady=10, sticky="e")

        self.option_sumber = ctk.CTkOptionMenu(self.tab_single, values=["Tokopedia", "Shopee", "Blibli", "OLX"], width=120)
        self.option_sumber.grid(row=0, column=3, padx=5, pady=10, sticky="w")

        self.btn_start_single = ctk.CTkButton(self.tab_single, text="▶ Mulai (Single)", command=self.mulai_single, width=120, font=ctk.CTkFont(weight="bold"))
        self.btn_start_single.grid(row=0, column=4, padx=(10, 10), pady=10, sticky="w")

        # --- ISI TAB BULK ---
        self.tab_bulk.grid_columnconfigure((0,1,2,3), weight=1)
        
        # Baris 1: Upload & Info
        self.btn_template = ctk.CTkButton(self.tab_bulk, text="⬇ Unduh Template Excel", command=self.unduh_template, fg_color="#228B22", hover_color="#006400")
        self.btn_template.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        self.btn_upload = ctk.CTkButton(self.tab_bulk, text="📂 Pilih File Excel", command=self.pilih_file, fg_color="gray", hover_color="#555555")
        self.btn_upload.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.label_file = ctk.CTkLabel(self.tab_bulk, text="Belum ada file terpilih.", text_color="red")
        self.label_file.grid(row=0, column=2, padx=5, pady=5, sticky="w")

        # FITUR BARU: Tombol Info Keyword
        self.btn_info_kw = ctk.CTkButton(self.tab_bulk, text="👁️ Info Keyword", command=self.lihat_keyword, state="disabled", fg_color="#E67E22", hover_color="#D35400")
        self.btn_info_kw.grid(row=0, column=3, padx=5, pady=5, sticky="ew")

        # Baris 2: Checkbox Platform & Mulai
        self.frame_chk = ctk.CTkFrame(self.tab_bulk, fg_color="transparent")
        self.frame_chk.grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky="w")
        
        self.label_platform = ctk.CTkLabel(self.frame_chk, text="Pilih Platform:", font=ctk.CTkFont(weight="bold"))
        self.label_platform.pack(side="left", padx=(5, 10))

        self.chk_tokped_var = ctk.StringVar(value="Tokopedia")
        self.chk_tokped = ctk.CTkCheckBox(self.frame_chk, text="Tokopedia", variable=self.chk_tokped_var, onvalue="Tokopedia", offvalue="")
        self.chk_tokped.pack(side="left", padx=5)

        self.chk_blibli_var = ctk.StringVar(value="Blibli")
        self.chk_blibli = ctk.CTkCheckBox(self.frame_chk, text="Blibli", variable=self.chk_blibli_var, onvalue="Blibli", offvalue="")
        self.chk_blibli.pack(side="left", padx=5)

        self.chk_olx_var = ctk.StringVar(value="OLX")
        self.chk_olx = ctk.CTkCheckBox(self.frame_chk, text="OLX", variable=self.chk_olx_var, onvalue="OLX", offvalue="")
        self.chk_olx.pack(side="left", padx=5)

        self.btn_start_bulk = ctk.CTkButton(self.tab_bulk, text="▶ Mulai Bulk", command=self.mulai_bulk, font=ctk.CTkFont(weight="bold"), fg_color="#8B008B", hover_color="#640064")
        self.btn_start_bulk.grid(row=1, column=3, padx=5, pady=5, sticky="ew")

        # ================= FRAME KONTROL STOP & WAKTU (Tetap Sama) =================
        self.frame_stop = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_stop.grid(row=2, column=0, padx=20, pady=(0, 5), sticky="ew")
        self.frame_stop.grid_columnconfigure(0, weight=1)
        self.frame_stop.grid_columnconfigure(3, weight=1)
        
        self.btn_stop = ctk.CTkButton(self.frame_stop, text="⏹ Batalkan Proses", command=self.stop_scraping, height=35, width=180, fg_color="#d93838", hover_color="#b32424", state="disabled", font=ctk.CTkFont(weight="bold", size=13))
        self.btn_stop.grid(row=0, column=1, padx=10, pady=5)

        self.label_timer = ctk.CTkLabel(self.frame_stop, text="⏱️ Waktu: 00:00", font=ctk.CTkFont(weight="bold", size=14), text_color="#1F538D")
        self.label_timer.grid(row=0, column=2, padx=10, pady=5, sticky="w")

        # ================= FRAME LOG & PROGRESS (Tetap Sama) =================
        self.frame_log = ctk.CTkFrame(self)
        self.frame_log.grid(row=3, column=0, padx=20, pady=(5, 10), sticky="nsew")
        self.frame_log.grid_rowconfigure(1, weight=1)
        self.frame_log.grid_columnconfigure(0, weight=1)

        self.frame_status = ctk.CTkFrame(self.frame_log, fg_color="transparent")
        self.frame_status.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        self.frame_status.grid_columnconfigure(1, weight=1)

        self.label_status = ctk.CTkLabel(self.frame_status, text="🟢 Status: Siap digunakan.", font=ctk.CTkFont(weight="bold"), text_color="black")
        self.label_status.grid(row=0, column=0, padx=5, sticky="w")

        self.progress_bar = ctk.CTkProgressBar(self.frame_status, mode="determinate")
        self.progress_bar.grid(row=0, column=1, padx=15, sticky="ew")
        self.progress_bar.set(0)

        self.label_pct = ctk.CTkLabel(self.frame_status, text="0%", font=ctk.CTkFont(weight="bold", size=14), text_color="#1F538D")
        self.label_pct.grid(row=0, column=2, padx=(0, 10), sticky="e")

        self.textbox_log = ctk.CTkTextbox(self.frame_log, font=ctk.CTkFont(family="Consolas", size=12), fg_color="#F0F0F0", text_color="black")
        self.textbox_log.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.textbox_log.insert("0.0", "Sistem siap. Silakan masukkan kata kunci, pilih sumber, dan klik Mulai.\n")
        self.textbox_log.configure(state="disabled")

        # ================= FRAME FOOTER =================
        self.frame_footer = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_footer.grid(row=4, column=0, padx=20, pady=(0, 20), sticky="ew")
        self.frame_footer.grid_columnconfigure(0, weight=1)

        self.btn_clear_log = ctk.CTkButton(self.frame_footer, text="Bersihkan Log", command=self.clear_log, width=120, fg_color="gray", hover_color="#555555")
        self.btn_clear_log.grid(row=0, column=0, sticky="w")

        self.btn_open_folder = ctk.CTkButton(self.frame_footer, text="📂 Buka Folder Hasil", command=self.buka_folder, width=150)
        self.btn_open_folder.grid(row=0, column=1, sticky="e")

    # --- FUNGSI UPDATE TIMER UI ---
    def update_timer(self):
        if self.timer_running and self.start_time_ui:
            elapsed = int(time.time() - self.start_time_ui)
            m, s = divmod(elapsed, 60)
            h, m = divmod(m, 60)
            if h > 0:
                self.label_timer.configure(text=f"⏱️ Waktu: {h:02d}:{m:02d}:{s:02d}")
            else:
                self.label_timer.configure(text=f"⏱️ Waktu: {m:02d}:{s:02d}")
            self.after(1000, self.update_timer)

    # --- FUNGSI LOGIKA APP & UTILITY ---
    def tulis_log(self, pesan):
        match = re.search(r'\[(\d+)/(\d+)\]', pesan)
        if match:
            try:
                current, total = int(match.group(1)), int(match.group(2))
                if total > 0:
                    pct = current / total
                    self.after(0, lambda: self.progress_bar.set(pct))
                    self.after(0, lambda: self.label_pct.configure(text=f"{int(pct * 100)}%"))
            except Exception: pass

        def update_ui():
            self.textbox_log.configure(state="normal")
            self.textbox_log.insert("end", f"[{time.strftime('%H:%M:%S')}] {pesan}\n")
            self.textbox_log.see("end")
            self.textbox_log.configure(state="disabled")
        self.after(0, update_ui)

    def set_status(self, teks, status_color="black"):
        self.after(0, lambda: self.label_status.configure(text=teks, text_color=status_color))

    def clear_log(self):
        self.textbox_log.configure(state="normal")
        self.textbox_log.delete("0.0", "end")
        self.textbox_log.insert("0.0", "Log dibersihkan. Sistem siap.\n")
        self.textbox_log.configure(state="disabled")

    def buka_folder(self):
        target_folder = os.path.join(os.getcwd(), "data")
        os.makedirs(target_folder, exist_ok=True)
        try:
            if sys.platform == "win32": os.startfile(target_folder)
            elif sys.platform == "darwin": subprocess.Popen(["open", target_folder])
            else: subprocess.Popen(["xdg-open", target_folder])
        except Exception as e:
            self.tulis_log(f"⚠️ Gagal membuka folder: {e}")

    def unduh_template(self):
        target_folder = os.path.join(os.getcwd(), "data")
        os.makedirs(target_folder, exist_ok=True)
        filepath = os.path.join(target_folder, "Template_Keyword.xlsx")
        pd.DataFrame(["Headset", "Speaker", "Webcam", "Printer"]).to_excel(filepath, index=False, header=False)
        self.tulis_log(f"✅ Template Excel dibuat: {filepath}")

    # FITUR BARU: Baca Excel & Simpan list Keyword sementara ke UI
    def pilih_file(self):
        file = filedialog.askopenfilename(title="Pilih File Excel", filetypes=[("Excel files", "*.xlsx *.xls")])
        if file:
            self.bulk_filepath = file
            filename = os.path.basename(file)
            self.label_file.configure(text=f"Terpilih: {filename}", text_color="green")
            
            try:
                df = pd.read_excel(self.bulk_filepath, header=None)
                raw_keywords = df[0].dropna().astype(str).tolist()
                
                self.saved_keywords = []
                for kw in raw_keywords:
                    cleaned = kw.strip()
                    if cleaned and cleaned.lower() != "keyword":
                        self.saved_keywords.append(cleaned)
                
                if self.saved_keywords:
                    self.btn_info_kw.configure(state="normal")
                    self.tulis_log(f"Berhasil mendeteksi {len(self.saved_keywords)} keyword dari file {filename}.")
                else:
                    self.tulis_log("⚠️ File excel kosong atau format tidak sesuai.")
            except Exception as e:
                self.tulis_log(f"⚠️ Error membaca Excel: {e}")

    # FITUR BARU: Popup Info Keyword
    def lihat_keyword(self):
        if not self.saved_keywords: return
            
        top = ctk.CTkToplevel(self)
        top.title("Daftar Keyword")
        top.geometry("350x450")
        top.transient(self) 
        
        lbl = ctk.CTkLabel(top, text=f"Total: {len(self.saved_keywords)} Keyword Tersimpan", font=ctk.CTkFont(weight="bold"))
        lbl.pack(pady=10)
        
        textbox = ctk.CTkTextbox(top, width=320, height=380, font=ctk.CTkFont(size=12))
        textbox.pack(padx=10, pady=10)
        
        for idx, kw in enumerate(self.saved_keywords, 1):
            textbox.insert("end", f"{idx}. {kw}\n")
        textbox.configure(state="disabled")

    def check_apakah_stop(self):
        return self.stop_flag

    def toggle_ui_state(self, is_running):
        state_normal = "disabled" if is_running else "normal"
        self.btn_start_single.configure(state=state_normal)
        self.btn_start_bulk.configure(state=state_normal)
        self.btn_upload.configure(state=state_normal)
        self.option_sumber.configure(state=state_normal)
        self.entry_keyword.configure(state=state_normal)
        self.combo_lokasi.configure(state=state_normal)
        self.chk_tokped.configure(state=state_normal)
        self.chk_blibli.configure(state=state_normal)
        self.chk_olx.configure(state=state_normal)
        
        # Disable/enable tombol info keyword sesuai kondisi file
        if not is_running and self.saved_keywords:
            self.btn_info_kw.configure(state="normal")
        else:
            self.btn_info_kw.configure(state="disabled")

        self.btn_stop.configure(state="normal" if is_running else "disabled")
        if not is_running:
            self.timer_running = False

    def stop_scraping(self):
        self.set_status("🔴 Status: Menghentikan proses...", "red")
        self.tulis_log("\n⚠️ PERINTAH STOP DITERIMA! Proses akan berhenti setelah task aktif saat ini selesai disave.")
        self.stop_flag = True
        self.btn_stop.configure(state="disabled")

    def format_waktu(self, detik):
        m, s = divmod(int(detik), 60)
        h, m = divmod(m, 60)
        if h > 0: return f"{h} jam {m} menit {s} detik"
        elif m > 0: return f"{m} menit {s} detik"
        else: return f"{s} detik"

    # --- MODE TUNGGAL ---
    def mulai_single(self):
        keyword = self.entry_keyword.get().strip()
        sumber = self.option_sumber.get()
        lokasi = self.combo_lokasi.get() # Ambil lokasi dinamis

        if not keyword:
            self.tulis_log("⚠️ Error: Kata kunci tidak boleh kosong!")
            return

        self.stop_flag = False
        self.set_status(f"🟡 Mengekstrak {sumber} di {lokasi}...", "#B8860B") 
        self.progress_bar.set(0)
        self.label_pct.configure(text="0%")
        
        self.label_timer.configure(text="⏱️ Waktu: 00:00")
        self.start_time_ui = time.time()
        self.timer_running = True
        self.update_timer()
        
        self.toggle_ui_state(is_running=True)

        self.tulis_log("-" * 50)
        self.tulis_log(f"🚀 MODE SINGLE: '{keyword}' via {sumber} (Lokasi: {lokasi})")
        
        thread = threading.Thread(target=self.proses_single_background, args=(keyword, sumber, lokasi))
        thread.daemon = True
        thread.start()

    def proses_single_background(self, keyword, sumber, lokasi):
        start_time = time.time() 
        try:
            # PENTING: Semua scraper menerima parameter tambahan: `lokasi`
            if sumber == "Blibli": scrape_blibli(keyword, lokasi=lokasi, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            elif sumber == "Tokopedia": scrape_tokopedia(keyword, lokasi=lokasi, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            elif sumber == "Shopee": scrape_shopee(keyword, lokasi=lokasi, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            elif sumber == "OLX":
                from olx_scraper import scrape_olx 
                scrape_olx(keyword, lokasi=lokasi, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            
            elapsed_time = time.time() - start_time 
            if self.stop_flag:
                self.set_status("🔴 Status: Dibatalkan.", "red")
                self.tulis_log(f"\n🛑 PROSES DIBATALKAN OLEH PENGGUNA.")
            else:
                self.set_status("🟢 Status: Selesai!", "green")
                self.after(0, lambda: self.progress_bar.set(1.0))
                self.after(0, lambda: self.label_pct.configure(text="100%"))
                self.tulis_log(f"\n✅ PROSES SELESAI DALAM WAKTU {self.format_waktu(elapsed_time)}!")
        except Exception as e:
            self.set_status("🔴 Status: Error", "red")
            self.tulis_log(f"\n❌ FATAL ERROR: {e}")
        finally:
            self.after(0, lambda: self.toggle_ui_state(is_running=False))

    # --- MODE BULK (EXCEL) ---
    def mulai_bulk(self):
        if not self.saved_keywords:
            self.tulis_log("⚠️ Error: Silakan pilih file Excel berisi keyword terlebih dahulu!")
            return

        # Cek platform apa saja yang dicentang
        sumber_list = []
        if self.chk_tokped_var.get(): sumber_list.append("Tokopedia")
        if self.chk_blibli_var.get(): sumber_list.append("Blibli")
        if self.chk_olx_var.get(): sumber_list.append("OLX")

        if len(sumber_list) == 0:
            self.tulis_log("⚠️ Error: Silakan centang minimal satu platform scraping (Tokopedia/Blibli/OLX)!")
            return

        lokasi = self.combo_lokasi.get() # Ambil lokasi dari dropdown

        self.stop_flag = False
        self.set_status(f"🟡 Bulk Scraping ({len(self.saved_keywords)} kata kunci) di {lokasi}...", "#8B008B") 
        self.progress_bar.set(0)
        self.label_pct.configure(text="0%")
        
        self.label_timer.configure(text="⏱️ Waktu: 00:00")
        self.start_time_ui = time.time()
        self.timer_running = True
        self.update_timer()

        self.toggle_ui_state(is_running=True)

        thread = threading.Thread(target=self.proses_bulk_background, args=(self.saved_keywords, sumber_list, lokasi))
        thread.daemon = True
        thread.start()

    def proses_bulk_background(self, keywords, sumber_list, lokasi):
        start_time_total = time.time() 
        total_tasks = len(keywords) * len(sumber_list)
        current_task = 0

        self.tulis_log("=" * 60)
        self.tulis_log(f"🚀 MEMULAI MODE BULK ({len(keywords)} Keyword, {len(sumber_list)} Platform)")
        self.tulis_log(f"📍 Target Lokasi: {lokasi}")
        self.tulis_log("=" * 60)

        for kw in keywords:
            for sumber in sumber_list:
                if self.stop_flag: break
                
                current_task += 1
                self.set_status(f"🟡 Bulk [{current_task}/{total_tasks}]: '{kw}' via {sumber}...", "#8B008B")
                self.tulis_log(f"\n{'='*40}\n📦 TASK [{current_task}/{total_tasks}]: {kw} -> {sumber}\n{'='*40}")
                
                self.after(0, lambda: self.progress_bar.set(0))
                self.after(0, lambda: self.label_pct.configure(text="0%"))

                start_time_task = time.time() 
                try:
                    # Lewatkan parameter `lokasi` ke scraper 
                    if sumber == "Tokopedia": scrape_tokopedia(kw, lokasi=lokasi, callback=self.tulis_log, stop_check=self.check_apakah_stop)
                    elif sumber == "Blibli": scrape_blibli(kw, lokasi=lokasi, callback=self.tulis_log, stop_check=self.check_apakah_stop)
                    elif sumber == "OLX":
                        from olx_scraper import scrape_olx 
                        scrape_olx(kw, lokasi=lokasi, callback=self.tulis_log, stop_check=self.check_apakah_stop)
                except Exception as e:
                    self.tulis_log(f"❌ Error pada '{kw}' via {sumber}: {e}")
                
                self.tulis_log(f"⏱️ Task selesai dalam: {self.format_waktu(time.time() - start_time_task)}")
                    
            if self.stop_flag: break

        waktu_str = self.format_waktu(time.time() - start_time_total)
        if self.stop_flag:
            self.set_status("🔴 Status: Bulk Dibatalkan.", "red")
            self.tulis_log(f"\n🛑 PROSES BULK DIBATALKAN. File sebelumnya aman.")
        else:
            self.set_status("🟢 Status: Bulk Selesai Total!", "green")
            self.after(0, lambda: self.progress_bar.set(1.0))
            self.after(0, lambda: self.label_pct.configure(text="100%"))
            self.tulis_log(f"\n✅ SELURUH PROSES BULK SELESAI DENGAN SEMPURNA DALAM WAKTU {waktu_str}!")

        self.after(0, lambda: self.toggle_ui_state(is_running=False))

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = MultiScraperApp()
    app.mainloop()