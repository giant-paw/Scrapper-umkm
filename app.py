import customtkinter as ctk
import threading
import time
import os
import subprocess
import sys
import multiprocessing
import re 

from blibli_scraper import scrape_blibli
from tokopedia_scraper import scrape_tokopedia 
from shopee_scraper import scrape_shopee 

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

class MultiScraperApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Geo-Scraper E-Commerce Pro v2.0")
        self.geometry("850x600")
        self.minsize(800, 500)

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.stop_flag = False

        # ================= FRAME HEADER =================
        self.frame_header = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_header.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="ew")
        
        self.label_title = ctk.CTkLabel(self.frame_header, text="E-Commerce Geo-Scraper v2.0", font=ctk.CTkFont(size=24, weight="bold"), text_color="#1F538D")
        self.label_title.pack()
        self.label_subtitle = ctk.CTkLabel(self.frame_header, text="Otomatisasi Ekstraksi Data & Pemetaan Spasial", text_color="gray")
        self.label_subtitle.pack()

        # ================= FRAME INPUT =================
        self.frame_input = ctk.CTkFrame(self)
        self.frame_input.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        self.frame_input.grid_columnconfigure((0,1,2,3,4,5), weight=1)

        self.label_keyword = ctk.CTkLabel(self.frame_input, text="Kata Kunci:", font=ctk.CTkFont(weight="bold"))
        self.label_keyword.grid(row=0, column=0, padx=(15, 5), pady=15, sticky="e")

        self.entry_keyword = ctk.CTkEntry(self.frame_input, placeholder_text="Contoh: Buku", width=160)
        self.entry_keyword.insert(0, "Semen")
        self.entry_keyword.grid(row=0, column=1, padx=5, pady=15, sticky="w")

        self.label_sumber = ctk.CTkLabel(self.frame_input, text="Sumber:", font=ctk.CTkFont(weight="bold"))
        self.label_sumber.grid(row=0, column=2, padx=(10, 5), pady=15, sticky="e")

        self.option_sumber = ctk.CTkOptionMenu(self.frame_input, values=["Tokopedia", "Shopee", "Blibli", "OLX"], width=120)
        self.option_sumber.grid(row=0, column=3, padx=5, pady=15, sticky="w")

        self.btn_start = ctk.CTkButton(self.frame_input, text="▶ Mulai", command=self.mulai_scraping, width=100, font=ctk.CTkFont(weight="bold"))
        self.btn_start.grid(row=0, column=4, padx=(10, 5), pady=15)

        self.btn_stop = ctk.CTkButton(self.frame_input, text="⏹ Stop", command=self.stop_scraping, width=100, 
                                      fg_color="#d93838", hover_color="#b32424", state="disabled", font=ctk.CTkFont(weight="bold"))
        self.btn_stop.grid(row=0, column=5, padx=(5, 15), pady=15)

        # ================= FRAME LOG & PROGRESS =================
        self.frame_log = ctk.CTkFrame(self)
        self.frame_log.grid(row=2, column=0, padx=20, pady=(5, 10), sticky="nsew")
        self.frame_log.grid_rowconfigure(1, weight=1)
        self.frame_log.grid_columnconfigure(0, weight=1)

        self.frame_status = ctk.CTkFrame(self.frame_log, fg_color="transparent")
        self.frame_status.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        self.frame_status.grid_columnconfigure(1, weight=1) # Agar progress bar melar

        self.label_status = ctk.CTkLabel(self.frame_status, text="🟢 Status: Siap digunakan.", font=ctk.CTkFont(weight="bold"), text_color="black")
        self.label_status.grid(row=0, column=0, padx=5, sticky="w")

        # --- PERUBAHAN KE DETERMINATE ---
        self.progress_bar = ctk.CTkProgressBar(self.frame_status, mode="determinate")
        self.progress_bar.grid(row=0, column=1, padx=15, sticky="ew")
        self.progress_bar.set(0)

        # --- TAMBAHAN LABEL PERSENTASE ---
        self.label_pct = ctk.CTkLabel(self.frame_status, text="0%", font=ctk.CTkFont(weight="bold", size=14), text_color="#1F538D")
        self.label_pct.grid(row=0, column=2, padx=(0, 10), sticky="e")

        self.textbox_log = ctk.CTkTextbox(self.frame_log, font=ctk.CTkFont(family="Consolas", size=12), fg_color="#F0F0F0", text_color="black")
        self.textbox_log.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.textbox_log.insert("0.0", "Sistem siap. Silakan masukkan kata kunci, pilih sumber, dan klik Mulai.\n")
        self.textbox_log.configure(state="disabled")

        # ================= FRAME FOOTER =================
        self.frame_footer = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_footer.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="ew")
        self.frame_footer.grid_columnconfigure(0, weight=1)

        self.btn_clear_log = ctk.CTkButton(self.frame_footer, text="Bersihkan Log", command=self.clear_log, width=120, fg_color="gray", hover_color="#555555")
        self.btn_clear_log.grid(row=0, column=0, sticky="w")

        self.btn_open_folder = ctk.CTkButton(self.frame_footer, text="📂 Buka Folder Hasil", command=self.buka_folder, width=150)
        self.btn_open_folder.grid(row=0, column=1, sticky="e")

    def tulis_log(self, pesan):
        # --- DETEKSI PERSENTASE DARI TEKS LOG ---
        # Mencari pola seperti "[1/50]" atau "[12/12]" di dalam kalimat log
        match = re.search(r'\[(\d+)/(\d+)\]', pesan)
        if match:
            try:
                current = int(match.group(1))
                total = int(match.group(2))
                if total > 0:
                    pct = current / total
                    # Update bar (0.0 s.d 1.0) dan Teks
                    self.after(0, lambda: self.progress_bar.set(pct))
                    self.after(0, lambda: self.label_pct.configure(text=f"{int(pct * 100)}%"))
            except Exception:
                pass

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
            if sys.platform == "win32":
                os.startfile(target_folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target_folder])
            else:
                subprocess.Popen(["xdg-open", target_folder])
        except Exception as e:
            self.tulis_log(f"⚠️ Gagal membuka folder: {e}")

    def check_apakah_stop(self):
        return self.stop_flag

    def mulai_scraping(self):
        keyword = self.entry_keyword.get().strip()
        sumber = self.option_sumber.get()

        if not keyword:
            self.tulis_log("⚠️ Error: Kata kunci tidak boleh kosong!")
            return

        self.stop_flag = False
        self.set_status(f"🟡 Status: Mengekstrak dari {sumber}...", "#B8860B") 
        
        # Reset progress bar sebelum mulai
        self.progress_bar.set(0)
        self.label_pct.configure(text="0%")

        self.btn_start.configure(state="disabled")
        self.option_sumber.configure(state="disabled")
        self.entry_keyword.configure(state="disabled")
        self.btn_stop.configure(state="normal") 

        self.tulis_log("-" * 50)
        self.tulis_log(f"🚀 MEMULAI PROSES: '{keyword}' via {sumber}")
        
        thread = threading.Thread(target=self.proses_background, args=(keyword, sumber))
        thread.daemon = True
        thread.start()

    def stop_scraping(self):
        self.set_status("🔴 Status: Menghentikan proses...", "red")
        self.tulis_log("\n⚠️ PERINTAH STOP DITERIMA! Menunggu browser untuk menutup dengan aman...")
        self.stop_flag = True
        self.btn_stop.configure(state="disabled")

    def proses_background(self, keyword, sumber):
        try:
            if sumber == "Blibli":
                scrape_blibli(keyword, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            elif sumber == "Tokopedia":
                scrape_tokopedia(keyword, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            elif sumber == "Shopee": 
                scrape_shopee(keyword, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            elif sumber == "OLX":
                from olx_scraper import scrape_olx 
                scrape_olx(keyword, callback=self.tulis_log, stop_check=self.check_apakah_stop)
            
            if self.stop_flag:
                self.set_status("🔴 Status: Dibatalkan.", "red")
                self.tulis_log(f"\n🛑 PROSES DIBATALKAN OLEH PENGGUNA.")
            else:
                self.set_status("🟢 Status: Selesai!", "green")
                # Paksa jadi 100% ketika benar-benar selesai
                self.after(0, lambda: self.progress_bar.set(1.0))
                self.after(0, lambda: self.label_pct.configure(text="100%"))
                self.tulis_log(f"\n✅ SELURUH PROSES SELESAI!")
                
        except Exception as e:
            self.set_status("🔴 Status: Terjadi Kesalahan", "red")
            self.tulis_log(f"\n❌ FATAL ERROR: {e}")
            
        finally:
            self.after(0, lambda: self.btn_start.configure(state="normal"))
            self.after(0, lambda: self.option_sumber.configure(state="normal"))
            self.after(0, lambda: self.entry_keyword.configure(state="normal"))
            self.after(0, lambda: self.btn_stop.configure(state="disabled"))

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = MultiScraperApp()
    app.mainloop()