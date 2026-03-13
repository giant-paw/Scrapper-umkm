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
CTX = "Bantul"
OUTPUT_PREFIX = "tokopedia"

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

def parse_card_texts(texts):
    texts = [clean_text(t) for t in texts if clean_text(t)]
    product_name, price, sold, shop_name, shop_location = "", "", "", "", ""
    for t in texts:
        if not price and t.lower().startswith("rp"): price = t
        if not sold and "terjual" in t.lower(): sold = t
    for i in range(len(texts) - 1):
        if "bantul" in texts[i + 1].lower():
            shop_name, shop_location = texts[i], texts[i + 1]
            break
    for t in texts:
        if t in [price, sold, shop_name, shop_location]: continue
        if len(t) >= 4:
            product_name = t
            break
    return {"product_name": product_name, "price": price, "sold": sold, "shop_name": shop_name, "shop_location": shop_location}

class TokopediaGeoScraper:
    def __init__(self, callback=None, stop_check=None):
        self.log_callback = callback
        self.stop_check = stop_check
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

    def safe_click(self, driver, by, selector, timeout=8):
        """Fungsi klik cerdas versi Selenium"""
        try:
            el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, selector)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", el)
            return True
        except:
            return False

    def scroll_and_load_more(self, driver, max_rounds=50):
        self.log("Memulai simulasi scroll ke bawah untuk memuat produk...")
        
        last_item_count = 0
        no_change_count = 0
        
        for i in range(max_rounds):
            if self.is_stopped(): break
            
            # Hitung jumlah produk yang ada di layar saat ini
            current_items = driver.find_elements(By.CSS_SELECTOR, 'img[alt="product-image"]')
            current_item_count = len(current_items)
            
            # Evaluasi apakah ada penambahan produk baru
            if current_item_count == last_item_count and current_item_count > 0:
                no_change_count += 1
                if no_change_count >= 2:
                    self.log(f"Mentok! Total produk berhenti di {current_item_count} item.")
                    break
            else:
                if current_item_count > last_item_count:
                    self.log(f"Produk termuat: {current_item_count} item...")
                last_item_count = current_item_count
                no_change_count = 0 
            
            # Scroll perlahan ke bawah (mirip mouse wheel)
            for _ in range(3):
                driver.execute_script("window.scrollBy(0, 1500);")
                time.sleep(0.8)
                
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            # Cari dan klik tombol "Muat Lebih Banyak"
            try:
                btn_xpath = '//button[contains(translate(text(), "MUAT LEBIH BANYAK", "muat lebih banyak"), "muat lebih banyak")]'
                btn = driver.find_element(By.XPATH, btn_xpath)
                if btn.is_displayed():
                    self.log(f"Klik 'Muat Lebih Banyak' #{i+1}")
                    self.safe_click(driver, By.XPATH, btn_xpath)
                    time.sleep(3.5)
            except:
                pass

    def scrape_tokopedia_logic(self, keyword):
        rows = []
        
        # Setup Selenium Chrome Anti-Bot
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        try:
            self.log(f"Mencari produk: {keyword}")
            driver.get("https://www.tokopedia.com")
            time.sleep(3)

            # Kotak Pencarian
            try:
                search_box = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="search"]')))
                search_box.send_keys(keyword)
                search_box.send_keys(Keys.ENTER)
                time.sleep(5)
            except Exception as e:
                self.log(f"Gagal menemukan kotak pencarian: {e}")
                driver.quit()
                return pd.DataFrame()

            self.log("Menerapkan Filter Lokasi (Kab. Bantul)...")
            
            # Klik 'Lihat Semua Lokasi'
            if not self.safe_click(driver, By.CSS_SELECTOR, '[data-testid="lnkSRPSeeAllLocFilter"]'): 
                self.log("Gagal membuka filter lokasi. Menyimpan data yang ada...")
                driver.quit()
                return pd.DataFrame()

            # Ketik "Kab. Bantul"
            try:
                loc_input = WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[aria-label="Cari lokasi"]')))
                loc_input.send_keys("Kab. Bantul")
                time.sleep(2)
            except:
                pass
            
            # Pilih "Kab. Bantul" dari hasil pencarian filter
            target_xpath = '//*[contains(text(),"Kab. Bantul")]/ancestor::*[self::label or self::div or self::li][1]'
            self.safe_click(driver, By.XPATH, target_xpath)
            time.sleep(1)
            
            # Terapkan
            self.safe_click(driver, By.CSS_SELECTOR, '[data-testid="btnSRPApplySeeAllFilter"]')
            time.sleep(5)

            # Eksekusi fungsi Scroll Mentok
            self.scroll_and_load_more(driver)

            self.log("Scraping semua data yang sudah terbuka...")
            product_imgs = driver.find_elements(By.CSS_SELECTOR, 'img[alt="product-image"]')
            seen_cards = set()
            
            for img in product_imgs:
                if self.is_stopped(): break
                try:
                    # Temukan bungkus terluar (card) dari produk ini
                    card = img.find_element(By.XPATH, "./ancestor::div[contains(., 'Kab. Bantul')][1]")
                    
                    # Ekstrak semua teks di dalam card
                    spans = card.find_elements(By.CSS_SELECTOR, "span")
                    texts = [span.get_attribute("innerText") for span in spans if span.get_attribute("innerText")]
                    
                    parsed = parse_card_texts(texts)
                    
                    if not parsed["shop_name"] or "bantul" not in parsed["shop_location"].lower(): continue

                    shop_name = clean_text(parsed["shop_name"])
                    row_key = (normalize_name(shop_name), normalize_name(parsed["product_name"]))
                    
                    if row_key in seen_cards: continue
                    seen_cards.add(row_key)

                    rows.append({
                        "shop_name": shop_name,
                        "shop_location": parsed["shop_location"],
                        "product_name": parsed["product_name"],
                        "price": parsed["price"],
                        "sold": parsed["sold"]
                    })
                    self.log(f"Ditemukan: {shop_name}")
                except: pass
                
        finally:
            driver.quit()
            
        return pd.DataFrame(rows).drop_duplicates(subset=["shop_name"])

    def run(self, keyword):
        df = self.scrape_tokopedia_logic(keyword)
        if df.empty:
            self.log("Tidak ada data ditemukan.")
            return

        self.log(f"Total toko unik ditemukan: {len(df)}. Memulai pengayaan Google Maps...")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        for i, row in df.iterrows():
            if self.is_stopped(): break
            shop = row["shop_name"]
            driver.get("https://www.google.com/maps/search/" + urllib.parse.quote(f"{shop}, {CTX}"))
            time.sleep(4)
            
            try:
                place_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/place/"]')
                if place_links:
                    place_links[0].click()
                    time.sleep(3)
            except: pass

            maps_url = driver.current_url
            alamat_lengkap = ""
            try:
                el_address = driver.find_element(By.CSS_SELECTOR, 'button[data-item-id="address"]')
                alamat_lengkap = el_address.text.strip()
            except: pass

            m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+),", maps_url)
            lat, lng = (float(m.group(1)), float(m.group(2))) if m else (None, None)
            
            geo_info = self.find_geojson_match(lat, lng)
            
            df.at[i, "latitude"] = lat
            df.at[i, "longitude"] = lng
            df.at[i, "idsls"] = geo_info["idsls"] if geo_info else ""
            df.at[i, "status"] = "DALAM_RING" if geo_info else "DILUAR_RING"
            df.at[i, "alamat_lengkap"] = alamat_lengkap
            df.at[i, "link_maps"] = maps_url
            
            self.log(f"Maps: {shop} -> {df.at[i, 'status']} | {alamat_lengkap[:30]}...")

        driver.quit()
        output_file = f"{OUTPUT_PREFIX}_{sanitize_filename(keyword)}_enriched.xlsx"
        df.to_excel(output_file, index=False)
        self.log(f"✅ Selesai! File disimpan: {output_file}")

def scrape_tokopedia(keyword, callback=None, stop_check=None):
    scraper = TokopediaGeoScraper(callback=callback, stop_check=stop_check)
    scraper.run(keyword)