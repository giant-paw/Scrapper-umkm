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
        self.geometry("900x650")
        self.minsize(850, 550)

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.stop_flag = False
        self.bulk_filepath = None

        # ================= FRAME HEADER =================
        self.frame_header = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_header.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="ew")
        
        self.label_title = ctk.CTkLabel(self.frame_header, text="E-Commerce Geo-Scraper v2.5", font=ctk.CTkFont(size=24, weight="bold"), text_color="#1F538D")
        self.label_title.pack()
        self.label_subtitle = ctk.CTkLabel(self.frame_header, text="Mode Pencarian Massal & Pemetaan Spasial", text_color="gray")
        self.label_subtitle.pack()

        # ================= TABS (SINGLE & BULK) =================
        self.tabview = ctk.CTkTabview(self, height=100)
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
        
        self.btn_template = ctk.CTkButton(self.tab_bulk, text="⬇ Unduh Template Excel", command=self.unduh_template, fg_color="#228B22", hover_color="#006400")
        self.btn_template.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="e")

        self.btn_upload = ctk.CTkButton(self.tab_bulk, text="📂 Pilih File Excel", command=self.pilih_file, fg_color="gray", hover_color="#555555")
        self.btn_upload.grid(row=0, column=1, padx=5, pady=10, sticky="w")

        self.label_file = ctk.CTkLabel(self.tab_bulk, text="Belum ada file terpilih.", text_color="red", width=200)
        self.label_file.grid(row=0, column=2, padx=5, pady=10, sticky="w")

        self.btn_start_bulk = ctk.CTkButton(self.tab_bulk, text="▶ Mulai Bulk (Tokped+Blibli+OLX)", command=self.mulai_bulk, font=ctk.CTkFont(weight="bold"), fg_color="#8B008B", hover_color="#640064")
        self.btn_start_bulk.grid(row=0, column=3, padx=(5, 10), pady=10, sticky="w")

        # ================= FRAME KONTROL STOP =================
        self.frame_stop = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_stop.grid(row=2, column=0, padx=20, pady=(0, 5), sticky="ew")
        
        self.btn_stop = ctk.CTkButton(self.frame_stop, text="⏹ STOP / BATALKAN PROSES", command=self.stop_scraping, height=35,
                                      fg_color="#d93838", hover_color="#b32424", state="disabled", font=ctk.CTkFont(weight="bold", size=14))
        self.btn_stop.pack(fill="x")

        # ================= FRAME LOG & PROGRESS =================
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

    # --- FUNGSI LOGIKA APP ---
    def tulis_log(self, pesan):
        match = re.search(r'\[(\d+)/(\d+)\]', pesan)
        if match:
            try:
                current = int(match.group(1))
                total = int(match.group(2))
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
        if not os.path.exists(target_folder):
            os.makedirs(target_folder)
        try:
            if sys.platform == "win32": os.startfile(target_folder)
            elif sys.platform == "darwin": subprocess.Popen(["open", target_folder])
            else: subprocess.Popen(["xdg-open", target_folder])
        except Exception as e:
            self.tulis_log(f"⚠️ Gagal membuka folder: {e}")

    def unduh_template(self):
        target_folder = os.path.join(os.getcwd(), "data")
        if not os.path.exists(target_folder):
            os.makedirs(target_folder)
        filepath = os.path.join(target_folder, "Template_Keyword.xlsx")
        
        df = pd.DataFrame({"Keyword": ["Headset", "Speaker", "Webcam", "Printer"]})
        df.to_excel(filepath, index=False)
        self.tulis_log(f"✅ Template Excel berhasil dibuat! Disimpan di: {filepath}")
        
        try:
            if sys.platform == "win32": os.startfile(filepath)
            elif sys.platform == "darwin": subprocess.Popen(["open", filepath])
        except: pass

    def pilih_file(self):
        file = filedialog.askopenfilename(title="Pilih File Excel", filetypes=[("Excel files", "*.xlsx *.xls")])
        if file:
            self.bulk_filepath = file
            filename = os.path.basename(file)
            self.label_file.configure(text=f"Terpilih: {filename}", text_color="green")
            self.tulis_log(f"File terpilih untuk Bulk: {filename}")

    def check_apakah_stop(self):
        return self.stop_flag

    def toggle_ui_state(self, is_running):
        state_normal = "disabled" if is_running else "normal"
        self.btn_start_single.configure(state=state_normal)
        self.btn_start_bulk.configure(state=state_normal)
        self.btn_upload.configure(state=state_normal)
        self.option_sumber.configure(state=state_normal)
        self.entry_keyword.configure(state=state_normal)
        self.btn_stop.configure(state="normal" if is_running else "disabled")

    def stop_scraping(self):
        self.set_status("🔴 Status: Menghentikan proses...", "red")
        self.tulis_log("\n⚠️ PERINTAH STOP DITERIMA! Proses akan berhenti setelah proses aktif saat ini selesai disave.")
        self.stop_flag = True
        self.btn_stop.configure(state="disabled")

    # --- MODE TUNGGAL ---
    def mulai_single(self):
        keyword = self.entry_keyword.get().strip()
        sumber = self.option_sumber.get()

        if not keyword:
            self.tulis_log("⚠️ Error: Kata kunci tidak boleh kosong!")
            return

        self.stop_flag = False
        self.set_status(f"🟡 Status: Mengekstrak {sumber}...", "#B8860B") 
        self.progress_bar.set(0)
        self.label_pct.configure(text="0%")
        self.toggle_ui_state(is_running=True)

        self.tulis_log("-" * 50)
        self.tulis_log(f"🚀 MODE SINGLE: '{keyword}' via {sumber}")
        
        thread = threading.Thread(target=self.proses_single_background, args=(keyword, sumber))
        thread.daemon = True
        thread.start()

    def proses_single_background(self, keyword, sumber):
        try:
            if sumber == "Blibli": scrape_blibli(keyword, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            elif sumber == "Tokopedia": scrape_tokopedia(keyword, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            elif sumber == "Shopee": scrape_shopee(keyword, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            elif sumber == "OLX":
                from olx_scraper import scrape_olx 
                scrape_olx(keyword, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            
            if self.stop_flag:
                self.set_status("🔴 Status: Dibatalkan.", "red")
                self.tulis_log(f"\n🛑 PROSES DIBATALKAN OLEH PENGGUNA.")
            else:
                self.set_status("🟢 Status: Selesai!", "green")
                self.after(0, lambda: self.progress_bar.set(1.0))
                self.after(0, lambda: self.label_pct.configure(text="100%"))
                self.tulis_log(f"\n✅ PROSES SELESAI!")
        except Exception as e:
            self.set_status("🔴 Status: Error", "red")
            self.tulis_log(f"\n❌ FATAL ERROR: {e}")
        finally:
            self.after(0, lambda: self.toggle_ui_state(is_running=False))

    # --- MODE BULK (EXCEL) ---
    def mulai_bulk(self):
        if not self.bulk_filepath:
            self.tulis_log("⚠️ Error: Silakan pilih file Excel terlebih dahulu!")
            return

        try:
            df = pd.read_excel(self.bulk_filepath)
            if "Keyword" not in df.columns:
                self.tulis_log("⚠️ Error: File Excel tidak memiliki kolom bernama 'Keyword'.")
                return
            keywords = df["Keyword"].dropna().astype(str).tolist()
        except Exception as e:
            self.tulis_log(f"⚠️ Error membaca Excel: {e}")
            return

        if not keywords:
            self.tulis_log("⚠️ Error: File Excel kosong atau tidak ada keyword valid.")
            return

        self.stop_flag = False
        self.set_status(f"🟡 Status: Memulai Bulk Scraping ({len(keywords)} kata kunci)...", "#8B008B") 
        self.progress_bar.set(0)
        self.label_pct.configure(text="0%")
        self.toggle_ui_state(is_running=True)

        thread = threading.Thread(target=self.proses_bulk_background, args=(keywords,))
        thread.daemon = True
        thread.start()

    def proses_bulk_background(self, keywords):
        sumber_list = ["Tokopedia", "Blibli", "OLX"]
        total_tasks = len(keywords) * len(sumber_list)
        current_task = 0

        self.tulis_log("=" * 60)
        self.tulis_log(f"🚀 MEMULAI MODE BULK ({len(keywords)} Keyword, 3 Platform)")
        self.tulis_log("=" * 60)

        for kw in keywords:
            for sumber in sumber_list:
                if self.stop_flag: break
                
                current_task += 1
                self.set_status(f"🟡 Bulk [{current_task}/{total_tasks}]: '{kw}' via {sumber}...", "#8B008B")
                self.tulis_log(f"\n{'='*40}\n📦 TASK [{current_task}/{total_tasks}]: {kw} -> {sumber}\n{'='*40}")
                
                # Reset progress bar visual di awal tiap sub-task
                self.after(0, lambda: self.progress_bar.set(0))
                self.after(0, lambda: self.label_pct.configure(text="0%"))

                try:
                    if sumber == "Tokopedia":
                        scrape_tokopedia(kw, callback=self.tulis_log, stop_check=self.check_apakah_stop)
                    elif sumber == "Blibli":
                        scrape_blibli(kw, callback=self.tulis_log, stop_check=self.check_apakah_stop)
                    elif sumber == "OLX":
                        from olx_scraper import scrape_olx 
                        scrape_olx(kw, callback=self.tulis_log, stop_check=self.check_apakah_stop)
                except Exception as e:
                    self.tulis_log(f"❌ Error pada '{kw}' via {sumber}: {e}")
                    
            if self.stop_flag: break

        if self.stop_flag:
            self.set_status("🔴 Status: Bulk Dibatalkan.", "red")
            self.tulis_log(f"\n🛑 PROSES BULK DIBATALKAN. File sebelumnya aman tersimpan di folder 'data'.")
        else:
            self.set_status("🟢 Status: Bulk Selesai Total!", "green")
            self.after(0, lambda: self.progress_bar.set(1.0))
            self.after(0, lambda: self.label_pct.configure(text="100%"))
            self.tulis_log(f"\n✅ SELURUH PROSES BULK SELESAI DENGAN SEMPURNA!")

        self.after(0, lambda: self.toggle_ui_state(is_running=False))

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = MultiScraperApp()
    app.mainloop()