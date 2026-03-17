import time
import re
import json
import urllib.parse
from difflib import SequenceMatcher
import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= CONFIG & UTILITY =================
GEOJSON_FILE = "bantul.geojson"  
CTX = "Yogyakarta"
OUTPUT_PREFIX = "blibli"

def sanitize_filename(text):
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "output"

def normalize_name(text):
    if not text: return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def clean_text(text):
    if not text: return ""
    return re.sub(r"\s+", " ", str(text)).strip()

class BlibliGeoScraper:
    def __init__(self, callback=None, stop_check=None):
        self.log_callback = callback
        self.stop_check = stop_check
        # Memuat GeoJSON
        with open(GEOJSON_FILE, "r", encoding="utf-8") as f:
            self.gj = json.load(f)

    def log(self, msg):
        if self.log_callback: self.log_callback(msg)
        print(msg)

    def is_stopped(self):
        return self.stop_check() if self.stop_check else False

    def point_in_poly(self, lat, lng, ring):
        x, y = lng, lat
        inside = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
            if (y1 > y) != (y2 > y):
                xinters = (x2 - x1) * (y - y1) / ((y2 - y1) + 1e-15) + x1
                if x < xinters: inside = not inside
        return inside

    def find_geojson_match(self, lat, lng):
        if lat is None or lng is None: return None
        for feature in self.gj.get("features", []):
            geom = feature.get("geometry", {})
            props = feature.get("properties", {})
            geom_type = geom.get("type")
            coords = geom.get("coordinates", [])
            try:
                if geom_type == "Polygon": rings = [coords[0]] if coords else []
                elif geom_type == "MultiPolygon": rings = [poly[0] for poly in coords if poly]
                else: rings = []
            except: rings = []

            for ring in rings:
                try:
                    lngs, lats = [p[0] for p in ring], [p[1] for p in ring]
                    if not (min(lats) <= lat <= max(lats) and min(lngs) <= lng <= max(lngs)): continue
                    if self.point_in_poly(lat, lng, ring):
                        return {
                            "idsls": props.get("idsls", ""),
                            "nama_kabupaten": props.get("nmkab", ""),
                            "nama_kecamatan": props.get("nmkec", ""),
                            "nama_desa": props.get("nmdesa", ""),
                            "nama_sls": props.get("nmsls", "")
                        }
                except: pass
        return None

    def safe_click(self, driver, element=None, by=None, selector=None, timeout=8):
        try:
            if not element:
                element = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, selector)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", element)
            return True
        except:
            return False

    def _handle_location_popup(self, driver):
        self.log("Mengecek popup lokasi Blibli...")
        try:
            nanti_btns = driver.find_elements(By.XPATH, "//button[contains(translate(text(), 'NANTI SAJA', 'nanti saja'), 'nanti saja')]")
            for btn in nanti_btns:
                if btn.is_displayed():
                    self.safe_click(driver, element=btn)
                    time.sleep(1)
                    break
        except: pass

    def _apply_filter(self, driver):
        self.log(f"Menerapkan filter Lokasi ({CTX})...")
        driver.execute_script("window.scrollBy(0, 300);")
        time.sleep(1)

        try:
            all_headers = driver.find_elements(By.CSS_SELECTOR, "div.filter-group__header")
            target_group = None
            for header in all_headers:
                if "lokasi toko" in header.text.lower():
                    target_group = header.find_element(By.XPATH, "..")
                    break
            
            if target_group:
                lihat_semua = target_group.find_elements(By.CSS_SELECTOR, "div.filter-checkbox-list__see-all")
                if lihat_semua and lihat_semua[0].is_displayed():
                    self.safe_click(driver, element=lihat_semua[0])
                    
                    try:
                        modal = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.filter-desktop-modal")))
                        
                        search_input = modal.find_elements(By.CSS_SELECTOR, "input.blu-text-field")
                        if search_input and search_input[0].is_displayed():
                            search_input[0].send_keys(CTX)
                            time.sleep(2)
                            
                        labels = modal.find_elements(By.CSS_SELECTOR, "label.blu-checkbox")
                        for lbl in labels:
                            if CTX.lower() in lbl.text.lower():
                                self.safe_click(driver, element=lbl)
                                time.sleep(0.5)
                                break

                        simpan_btns = modal.find_elements(By.XPATH, ".//button[contains(translate(text(), 'SIMPAN', 'simpan'), 'simpan')]")
                        for btn in simpan_btns:
                            if btn.is_displayed() and btn.is_enabled():
                                self.safe_click(driver, element=btn)
                                self.log(f"Filter {CTX} BERHASIL diterapkan lewat modal.")
                                time.sleep(4)
                                return True
                    except Exception as e:
                        self.log(f"Gagal interaksi dengan modal filter: {e}")
                else:
                    direct_checks = target_group.find_elements(By.CSS_SELECTOR, "label")
                    for check in direct_checks:
                        if CTX.lower() in check.text.lower() and check.is_displayed():
                            self.safe_click(driver, element=check)
                            self.log(f"Filter {CTX} (Langsung) BERHASIL diterapkan.")
                            time.sleep(4)
                            return True
        except Exception as e:
            self.log(f"Gagal menerapkan filter otomatis: {e}")
        return False

    def scrape_blibli_logic(self, keyword):
        rows = []
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        try:
            self.log(f"Mencari produk di Blibli: {keyword}")
            driver.get("https://www.blibli.com/")
            time.sleep(3)

            # Pencarian
            try:
                search_box = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Cari'], input[type='search']"))
                )
                search_box.click()
                search_box.send_keys(keyword)
                search_box.send_keys(Keys.ENTER)
                time.sleep(5)
            except:
                self.log("⚠️ Kolom pencarian terblokir atau tidak ditemukan.")
                return pd.DataFrame()

            self._handle_location_popup(driver)
            
            for _ in range(3):
                if self.is_stopped(): break
                if self._apply_filter(driver): break

            seen_shops = set()
            current_page = 1
            max_pages = 10
            cards_data = []

            # FASE 1: Kumpulkan URL produk dari halaman
            while current_page <= max_pages:
                if self.is_stopped(): break

                self.log(f"\n--- Memproses Halaman {current_page} ---")
                
                self.log("Simulasi scroll ke bawah untuk memuat kartu produk...")
                for _ in range(5):
                    driver.execute_script("window.scrollBy(0, 1000);")
                    time.sleep(0.8)
                
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)

                product_cards = driver.find_elements(By.CSS_SELECTOR, "div.product-list__card, div[class*='product-card']")
                self.log(f"Menemukan {len(product_cards)} produk. Mulai mengumpulkan URL...")
                
                for card in product_cards:
                    if self.is_stopped(): break
                    try:
                        links = card.find_elements(By.TAG_NAME, "a")
                        if not links: continue
                        url = links[0].get_attribute("href")
                        
                        if url and url.startswith("/"): url = "https://www.blibli.com" + url
                        if url:
                            cards_data.append({"url": url})
                    except: pass
                
                # Coba pindah halaman
                if current_page < max_pages and not self.is_stopped():
                    try:
                        next_page_xpath = f"//button[contains(@class, 'blu-pagination__button') and text()='{current_page + 1}']"
                        next_btns = driver.find_elements(By.XPATH, next_page_xpath)
                        if next_btns and next_btns[0].is_displayed():
                            self.log(f"Pindah ke halaman {current_page + 1}...")
                            self.safe_click(driver, element=next_btns[0])
                            time.sleep(4)
                            current_page += 1
                        else:
                            self.log("Mentok! Tidak ada halaman selanjutnya.")
                            break
                    except: break
                else: break

            # FASE 2: Buka URL satu per satu untuk ambil data lengkap & nama toko
            self.log(f"Membuka detail dari {len(cards_data)} produk untuk mengekstrak Nama Toko asli...")
            for idx, item in enumerate(cards_data):
                if self.is_stopped(): break
                try:
                    driver.get(item["url"])
                    time.sleep(2.5) 
                    
                    product_name = ""
                    try:
                        title_el = driver.find_element(By.CSS_SELECTOR, "h1, .product-name")
                        product_name = clean_text(title_el.text)
                    except: pass

                    shop_selectors = [
                        "span.seller-name__name",      
                        "span[class*='seller-name']",  
                        "div[class*='merchant-name']",
                        "a[class*='merchant-name']",
                        "h2[class*='merchant-name']",
                        "[data-testid='merchant-name']",
                        "div.merchant-details__name",
                        ".seller-name__name"
                    ]
                    
                    shop_name = ""
                    for sel in shop_selectors:
                        try:
                            shop_elem = driver.find_element(By.CSS_SELECTOR, sel)
                            if shop_elem.is_displayed():
                                shop_name = clean_text(shop_elem.get_attribute("innerText"))
                                break
                        except: pass
                    
                    if not shop_name or shop_name.lower() in ["kab. bantul", "yogyakarta", "kota yogyakarta", "sleman"]:
                        continue 
                        
                    if shop_name in seen_shops:
                        continue
                        
                    seen_shops.add(shop_name)
                    
                    rows.append({
                        "shop_name": shop_name
                    })
                    self.log(f"  [{idx+1}/{len(cards_data)}] Ditemukan Toko: {shop_name}")
                except Exception:
                    pass 
        finally:
            driver.quit()
            
        return pd.DataFrame(rows).drop_duplicates(subset=["shop_name"])

    def run(self, keyword):
        df = self.scrape_blibli_logic(keyword)
        if df.empty:
            self.log("Tidak ada data ditemukan.")
            return

        self.log(f"Total toko unik ditemukan: {len(df)}. Memulai pengayaan Google Maps...")
        options = webdriver.ChromeOptions()
        # options.add_argument("--headless") # Aktifkan jika ingin Maps di background
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        final_rows = []

        for i, row in df.iterrows():
            if self.is_stopped(): break
            shop = row["shop_name"]
            
            # Format query: "Nama Toko yogyakarta"
            maps_query = f"{shop} {CTX}"
            self.log(f"Mencari di Maps: {maps_query}")
            
            driver.get("https://www.google.com/maps/search/" + urllib.parse.quote(maps_query))
            time.sleep(4)
            
            # Klik hasil pertama jika muncul dalam bentuk daftar
            try:
                place_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/place/"]')
                if place_links:
                    driver.execute_script("arguments[0].click();", place_links[0])
                    time.sleep(3)
            except: pass

            maps_url = driver.current_url
            
            # Ambil Nama Tempat di Maps
            maps_place_name = ""
            try:
                h1 = driver.find_element(By.CSS_SELECTOR, "h1")
                maps_place_name = clean_text(h1.text)
            except: 
                maps_place_name = shop

            # Ambil Alamat
            maps_address = ""
            try:
                btn_addr = driver.find_element(By.CSS_SELECTOR, 'button[data-item-id="address"]')
                maps_address = btn_addr.get_attribute("aria-label").replace("Alamat: ", "").strip()
                if not maps_address:
                    maps_address = clean_text(btn_addr.text)
            except: pass

            # Ambil Nomor Telepon
            phone = ""
            try:
                btn_phone = driver.find_element(By.CSS_SELECTOR, 'button[data-item-id^="phone:tel:"]')
                phone = btn_phone.get_attribute("aria-label").replace("Nomor telepon: ", "").strip()
                if not phone:
                    phone = clean_text(btn_phone.text)
            except: pass

            # Ekstrak Lat & Lng dari URL
            m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+),", maps_url)
            lat, lng = (float(m.group(1)), float(m.group(2))) if m else (None, None)
            
            # CEK GEOJSON & RING MAPS (Yang Tadi Terlewat)
            geo_info = self.find_geojson_match(lat, lng)
            
            if lat is None:
                status = "NOT_FOUND"
            else:
                status = "DALAM_RING" if geo_info else "DILUAR_RING"
            
            # Cek kecocokan (Similarity)
            similarity = SequenceMatcher(None, shop.lower(), maps_place_name.lower()).ratio()
            if similarity >= 0.8:
                match_quality = "TINGGI"
            elif similarity >= 0.5:
                match_quality = "SEDANG"
            else:
                match_quality = "RENDAH"

            # Simpan hasil gabungan (Template CSV + GeoJSON)
            final_rows.append({
                "shop_name": shop,
                "maps_query": maps_query,
                "maps_place_name": maps_place_name,
                "maps_address": maps_address,
                "name_similarity": round(similarity, 4),
                "match_quality": match_quality,
                "latitude": lat,
                "longitude": lng,
                "phone": phone,
                "website": "",  # Sesuai template
                "email": "",    # Sesuai template
                "maps_url": maps_url,
                "idsls": geo_info["idsls"] if geo_info else "",                 # <-- KEMBALI!
                "nama_kecamatan": geo_info["nama_kecamatan"] if geo_info else "", # <-- KEMBALI!
                "nama_desa": geo_info["nama_desa"] if geo_info else "",           # <-- KEMBALI!
                "nama_sls": geo_info["nama_sls"] if geo_info else "",             # <-- KEMBALI!
                "status": status                                                # <-- KEMBALI!
            })
            
            self.log(f"Maps: {shop} -> {status} | Sim: {round(similarity, 2)} | Telp: {phone}")

        driver.quit()
        
        # Simpan ke DataFrame dengan urutan kolom yang sempurna
        output_df = pd.DataFrame(final_rows, columns=[
            "shop_name", "maps_query", "maps_place_name", "maps_address", 
            "name_similarity", "match_quality", "latitude", "longitude", 
            "phone", "website", "email", "maps_url", 
            "idsls", "nama_kecamatan", "nama_desa", "nama_sls", "status"
        ])
        
        output_file = f"{OUTPUT_PREFIX}_{sanitize_filename(keyword)}_enriched.xlsx"
        output_df.to_excel(output_file, index=False)
        self.log(f"✅ Selesai! File disimpan: {output_file}")

def scrape_blibli(keyword, callback=None, stop_check=None):
    scraper = BlibliGeoScraper(callback=callback, stop_check=stop_check)
    scraper.run(keyword)