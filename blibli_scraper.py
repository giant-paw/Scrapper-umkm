import re
import pandas as pd
import time
import os
import geopandas as gpd
from shapely.geometry import Point
from playwright.sync_api import sync_playwright

# ================= CONFIG =================
GEOJSON_FILE = 'bantul.geojson'
OUTPUT_PREFIX = 'blibli'
OUTPUT_FOLDER = 'data'

# ================= UTILITY =================
def sanitize_filename(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_") or "output"

# ================= MAIN SCRAPER CLASS =================
class BlibliGeoScraper:
    def __init__(self, callback=None, stop_check=None):
        self.log_callback = callback
        self.stop_check = stop_check

    def log(self, *args):
        msg = " ".join(map(str, args))
        print(msg) 
        if self.log_callback:
            self.log_callback(msg)

    def is_stopped(self) -> bool:
        return self.stop_check() if self.stop_check else False

    def _handle_location_popup(self, page) -> bool:
        """Menutup popup 'Aktifkan lokasi' jika muncul."""
        self.log(">>> Mengecek popup lokasi <<<")
        try:
            nanti_btn = page.locator("button.blu-button").filter(has_text=re.compile(r"Nanti saja", re.IGNORECASE)).first
            if nanti_btn.is_visible(timeout=3000):
                self.log("  Menemukan tombol 'Nanti saja'. Mengklik...")
                nanti_btn.click()
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass
        return False

    def _apply_filter(self, page) -> bool:
        """Mencoba menerapkan filter lokasi 'Kab. Bantul' secara otomatis."""
        self.log(">>> Menerapkan filter 'Kab. Bantul' <<<")
        page.evaluate("window.scrollBy(0, 300)")
        page.wait_for_timeout(1000)

        try:
            all_headers = page.locator("div.filter-group__header").all()
            target_group = None
            
            for header in all_headers:
                if "lokasi toko" in header.text_content().lower():
                    target_group = header.locator("xpath=..")
                    break
            
            if target_group:
                lihat_semua = target_group.locator("div.filter-checkbox-list__see-all").first
                if lihat_semua.is_visible():
                    lihat_semua.scroll_into_view_if_needed()
                    lihat_semua.click()
                    
                    modal = page.locator("div.filter-desktop-modal").first
                    modal.wait_for(state="visible", timeout=3000)
                    
                    # Cek langsung di populer
                    checkbox_label = modal.locator("label.blu-checkbox").filter(has_text=re.compile(r"^Kab. Bantul$", re.IGNORECASE)).first
                    if checkbox_label.is_visible():
                        checkbox_label.click()
                        page.wait_for_timeout(500)
                    else:
                        # Cari manual
                        search_input = modal.locator("input.blu-text-field").first
                        if search_input.is_visible():
                            search_input.click()
                            search_input.fill("Kab. Bantul")
                            page.wait_for_timeout(2000)
                            
                            checkbox_label = modal.locator("label.blu-checkbox").filter(has_text=re.compile(r"^Kab. Bantul$", re.IGNORECASE)).first
                            if checkbox_label.is_visible():
                                checkbox_label.click()
                                page.wait_for_timeout(500)

                    simpan_btn = modal.locator("button").filter(has_text=re.compile(r"Simpan", re.IGNORECASE)).first
                    if simpan_btn.is_visible() and not simpan_btn.is_disabled():
                        simpan_btn.click()
                        self.log("  Filter Kab. Bantul BERHASIL diterapkan.")
                        page.wait_for_timeout(4000)
                        return True

                else:
                    # Fallback jika checkbox sudah ada di luar modal
                    direct_check = target_group.locator("label").filter(has_text="Kab. Bantul").first
                    if direct_check.is_visible():
                        direct_check.click()
                        self.log("  Filter Kab. Bantul (Langsung) BERHASIL diterapkan.")
                        page.wait_for_timeout(4000)
                        return True
                        
        except Exception as e:
            self.log(f"  Gagal menerapkan filter otomatis: {e}")

        self.log(">>> GAGAL filter otomatis. Melanjutkan tanpa filter khusus... <<<")
        return False

    def extract_blibli_shops(self, keyword: str, p) -> list:
        """Mengekstrak data produk dan toko dari Blibli."""
        final_data = []
        seen_shops = set()
        
        browser = p.chromium.launch(
            headless=False, 
            channel="msedge", # <-- Tambahan ajaib ini
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )

        context = browser.new_context(no_viewport=True) 
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get:()=>undefined})")
        page = context.new_page()

        try:
            self.log("Membuka browser... Navigasi ke Blibli")
            page.goto("https://www.blibli.com/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            
            # Pencarian
            inp = page.locator("input[placeholder*='Cari'], input[type='search'], input[data-testid*='search']").first
            if inp.is_visible():
                inp.click()
                inp.fill(keyword)
                page.keyboard.press("Enter")
                page.wait_for_timeout(3000)
            else:
                self.log("⚠️ Kolom pencarian tidak ditemukan.")
                return []

            self._handle_location_popup(page)
            
            try:
                page.wait_for_selector("div.els-product, div[class*='product']", timeout=15000)
            except Exception:
                self.log("Peringatan: Hasil pencarian lambat dimuat.")

            # Terapkan filter lokasi
            for _ in range(3):
                if self.is_stopped(): break
                if self._apply_filter(page): break
            
            current_page = 1
            max_pages = 10

            while current_page <= max_pages:
                if self.is_stopped():
                    self.log("🛑 Proses Blibli dihentikan oleh pengguna.")
                    break

                self.log(f"\n>>> Memproses Halaman {current_page} <<<")
                page.wait_for_timeout(3000)
                
                product_cards = page.locator("div.product-list__card").all()
                self.log(f"  Menemukan {len(product_cards)} produk di halaman ini.")
                
                for idx, card in enumerate(product_cards):
                    try:
                        product_name_elem = card.locator("span.els-product__title").first
                        product_name = product_name_elem.text_content().strip() if product_name_elem.count() > 0 else "N/A"
                        
                        shop_elem = card.locator("span.els-product__seller-name").first
                        shop_name = shop_elem.text_content().strip() if shop_elem.count() > 0 else "N/A"
                        
                        # Deduplikasi toko
                        if shop_name in seen_shops or shop_name == "N/A":
                            continue
                        
                        price_elem = card.locator("div.els-product__fixed-price span").last
                        price = "Rp " + price_elem.text_content().strip() if price_elem.count() > 0 else "N/A"
                        
                        rating_elem = card.locator("div.els-product__seller-rating__text").first
                        rating = "N/A"
                        if rating_elem.count() > 0:
                            rating_match = re.search(r"(\d+[,\.]\d+)", rating_elem.text_content().strip())
                            rating = rating_match.group(1) if rating_match else rating_elem.text_content().strip()
                        
                        sold_elem = card.locator("div.els-product__sold").first
                        sold = sold_elem.text_content().strip() if sold_elem.count() > 0 else "N/A"
                        
                        if product_name != "N/A":
                            final_data.append({
                                "Product Name": product_name,
                                "Shop Name": shop_name,
                                "Sold Count": sold,
                                "Price": price,
                                "Rating": rating
                            })
                            seen_shops.add(shop_name)
                            self.log(f"  [{idx+1}] {product_name[:30]}... | Toko: {shop_name}")
                    except Exception:
                        continue
                
                # Navigasi ke halaman berikutnya
                if current_page < max_pages and not self.is_stopped():
                    try:
                        next_page_btn = page.locator("button.blu-pagination__button").filter(has_text=str(current_page + 1)).first
                        if next_page_btn.is_visible():
                            next_page_btn.scroll_into_view_if_needed()
                            page.wait_for_timeout(1000)
                            next_page_btn.click()
                            current_page += 1
                        else:
                            break
                    except Exception:
                        break
                else:
                    break

        finally:
            browser.close()
            
        return final_data

    def enrich_google_maps(self, unique_data_list: list, p) -> list:
        """Mencari alamat dan koordinat fisik dari Google Search untuk setiap toko."""
        if not unique_data_list: return []
        
        self.log(f"\n>>> MEMULAI PENCARIAN GOOGLE UNTUK {len(unique_data_list)} TOKO <<<")
        
        browser = p.chromium.launch(
            headless=False, 
            channel="msedge", # <-- Tambahan ajaib ini
            args=["--start-maximized", "--disable-blink-features=AutomationControlled", "--mute-audio"]
        )
        
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        try:
            for idx, item in enumerate(unique_data_list):
                if self.is_stopped():
                    self.log("🛑 Pencarian Google dihentikan.")
                    break

                shop_name = item["Shop Name"]
                self.log(f"  [{idx+1}/{len(unique_data_list)}] Mencari di Google: {shop_name}")
                
                shop_data = {
                    "Google Title": "N/A", "Google Address": "Not Found", 
                    "Google Phone": "Not Found", "Google Coordinates": "Not Found"
                }
                
                try:
                    page.goto("https://www.google.com/", timeout=60000)
                    search_box = page.locator("textarea[name='q'], input[name='q']").first
                    
                    if search_box.is_visible():
                        clean_name = shop_name.replace("Flagship Store", "").replace("Official Store", "").strip()
                        search_box.fill(f"{clean_name} yogyakarta")
                        page.keyboard.press("Enter")
                        page.wait_for_timeout(3000)
                        
                        # Ambil Judul Google
                        title_elem = page.locator("div[data-attrid='title']").first
                        if title_elem.is_visible(): shop_data["Google Title"] = title_elem.text_content().strip()

                        # Ambil Alamat
                        addr_elem = page.locator("div[data-attrid='kc:/location/location:address']").first
                        if addr_elem.is_visible():
                            shop_data["Google Address"] = addr_elem.text_content().replace("Alamat: ", "").replace("Address: ", "").strip()
                        else:
                            body_txt = page.locator("body").inner_text() 
                            for line in body_txt.split('\n'):
                                if line.strip().startswith("Alamat:"):
                                    shop_data["Google Address"] = line.replace("Alamat:", "").strip()
                                    break

                        # Ambil Nomor Telepon
                        phone_elem = page.locator("div[data-attrid='kc:/collection/locations:contact_phone']").first
                        if phone_elem.is_visible():
                            shop_data["Google Phone"] = phone_elem.text_content().replace("Telepon: ", "").replace("Phone: ", "").replace("Nomer tilpun: ", "").strip()

                        # Ekstraksi Koordinat Maps
                        map_url = ""
                        potential_maps = page.locator("[data-url]").all()
                        for pm in potential_maps:
                            url = pm.get_attribute("data-url")
                            if url and "maps.google" in url and ("center" in url or "3d" in url):
                                map_url = url
                                break
                                
                        if not map_url:
                            directions = page.locator("[aria-label*='Jurusan'], [aria-label*='Rute'], [aria-label*='Directions']").first
                            if directions.is_visible():
                                map_url = directions.get_attribute("href") or directions.locator("..").get_attribute("href")

                        if not map_url:
                            place_link = page.locator("a[href*='/maps/place/']").first
                            if place_link.count() > 0:
                                href = place_link.get_attribute("href")
                                if href:
                                    if href.startswith("/"): href = "https://www.google.com" + href
                                    try:
                                        page.goto(href, timeout=30000, wait_until="domcontentloaded")
                                        for _ in range(10): 
                                            curr_url = page.evaluate("window.location.href")
                                            if "3d" in curr_url and "4d" in curr_url:
                                                map_url = curr_url
                                                break
                                            page.wait_for_timeout(1000)
                                    except Exception: pass

                        if map_url:
                            matches = re.findall(r"3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", map_url)
                            if matches:
                                shop_data["Google Coordinates"] = f"{matches[0][0]}, {matches[0][1]}"
                            else:
                                match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', map_url)
                                if match: shop_data["Google Coordinates"] = f"{match.group(1)}, {match.group(2)}"

                except Exception as e:
                    self.log(f"  Error ekstraksi {shop_name}: {e}")
                
                item.update(shop_data)
                self.log(f"  Google Coord: {shop_data['Google Coordinates']}")
                page.wait_for_timeout(1500)

        finally:
            browser.close()
            
        return unique_data_list

    def map_and_save_data(self, data_list: list, keyword: str):
        """Memetakan data dengan GeoPandas (Spatial Join Cepat) dan menyimpan ke Excel."""
        self.log("\n>>> MEMULAI PEMETAAN GEOSPASIAL <<<")
        if not data_list: return

        df = pd.DataFrame(data_list)
        if not os.path.exists(GEOJSON_FILE):
            self.log(f"  Error: File GeoJSON '{GEOJSON_FILE}' tidak ditemukan! Menyimpan data mentah...")
            df.to_excel(f"{OUTPUT_PREFIX}_{sanitize_filename(keyword)}_mentah.xlsx", index=False)
            return

        peta_rt = gpd.read_file(GEOJSON_FILE)
        
        # Bersihkan spasi di nama kolom
        df.columns = df.columns.str.strip()
        kolom_kordinat = 'Google Coordinates'

        # Filter baris yang punya koordinat valid
        df_valid = df[df[kolom_kordinat].astype(str).str.contains(',', na=False)].copy()
        df_valid = df_valid[df_valid[kolom_kordinat] != 'Not Found'].copy()

        if df_valid.empty:
            self.log("  Tidak ada toko dengan titik koordinat valid. Menyimpan data mentah...")
            df.to_excel(f"{OUTPUT_PREFIX}_{sanitize_filename(keyword)}_mentah.xlsx", index=False)
            return

        # Pisahkan lat/lng dan buat GeoDataFrame
        coords = df_valid[kolom_kordinat].str.split(',', expand=True)
        df_valid['latitude'] = pd.to_numeric(coords[0], errors='coerce')
        df_valid['longitude'] = pd.to_numeric(coords[1], errors='coerce')
        df_valid.dropna(subset=['latitude', 'longitude'], inplace=True)

        # Proses vektorisasi Spatial Join yang sangat cepat
        geometry = [Point(xy) for xy in zip(df_valid['longitude'], df_valid['latitude'])]
        gdf_titik = gpd.GeoDataFrame(df_valid, geometry=geometry, crs="EPSG:4326")
        peta_rt = peta_rt.to_crs(epsg=4326)
        
        hasil_join = gpd.sjoin(gdf_titik, peta_rt, predicate='within', how='left')

        # Siapkan kolom output sesuai standar BPS
        def get_col(df_source, col_name):
            return df_source[col_name] if col_name in df_source.columns else ""

        output_df = pd.DataFrame()
        output_df['nama_usaha'] = get_col(hasil_join, 'Google Title')
        output_df['nama_komersial_usaha'] = get_col(hasil_join, 'Shop Name')
        output_df['alamat'] = get_col(hasil_join, 'Google Address')
        
        for col in ['kdkab', 'kdkec', 'kddesa', 'kdsls', 'kdsubsls']:
            output_df[col] = get_col(hasil_join, col)
            
        output_df['nomor_telepon'] = get_col(hasil_join, 'Google Phone')
        output_df['latitude'] = get_col(hasil_join, 'latitude')
        output_df['longitude'] = get_col(hasil_join, 'longitude')
        output_df['kegiatan_usaha'] = "Jualan di Blibli"
        output_df['sumber_data'] = "Blibli"
        
        # Tambahan Info Produk (Opsional, sangat berguna)
        output_df['produk_terjual'] = get_col(hasil_join, 'Sold Count')
        output_df['harga_produk'] = get_col(hasil_join, 'Price')

        # Buat folder dan simpan
        if not os.path.exists(OUTPUT_FOLDER): os.makedirs(OUTPUT_FOLDER)
        output_filename = os.path.join(OUTPUT_FOLDER, f"dir_usaha_{OUTPUT_PREFIX}_{sanitize_filename(keyword)}.xlsx")

        if os.path.exists(output_filename):
            try:
                existing_df = pd.read_excel(output_filename)
                combined_df = pd.concat([existing_df, output_df], ignore_index=True)
                combined_df.to_excel(output_filename, index=False, engine='openpyxl')
                self.log(f"✅ Data ditambahkan ke '{output_filename}'. Total: {len(combined_df)} baris.")
            except Exception as e:
                backup = os.path.join(OUTPUT_FOLDER, f"backup_{OUTPUT_PREFIX}_{int(time.time())}.xlsx")
                output_df.to_excel(backup, index=False, engine='openpyxl')
                self.log(f"⚠️ File utama dikunci. Disimpan sebagai backup: {backup}")
        else:
            output_df.to_excel(output_filename, index=False, engine='openpyxl')
            self.log(f"✅ Data baru disimpan di '{output_filename}'. Total: {len(output_df)} baris.")

    def run(self, keyword: str):
        self.log(f"--- Memulai Ekstraksi Blibli untuk: {keyword} ---")
        
        # Kita panggil sync_playwright() satu kali di tingkat atas agar efisien
        with sync_playwright() as p:
            # 1. Ekstrak Blibli
            data_list = self.extract_blibli_shops(keyword, p)
            if self.is_stopped() or not data_list: return
            
            # 2. Enrich dengan Google Search
            enriched_data = self.enrich_google_maps(data_list, p)
            if self.is_stopped() or not enriched_data: return
            
            # 3. GeoPandas Mapping & Save
            self.map_and_save_data(enriched_data, keyword)


# ================= ENTRY POINT UNTUK GUI =================
def scrape_blibli(keyword, callback=None, stop_check=None):
    if not keyword: return
    scraper = BlibliGeoScraper(callback=callback, stop_check=stop_check)
    scraper.run(keyword)

if __name__ == "__main__":
    kw = input("Keyword Blibli: ").strip()
    scrape_blibli(kw)