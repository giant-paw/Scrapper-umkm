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
GEOJSON_FILE = "idsls fix.geojson"
CTX = "Bantul"
OUTPUT_PREFIX = "olx"

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

class OLXGeoScraper:
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
        """Fungsi klik cerdas versi Selenium"""
        try:
            if not element:
                element = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, selector)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", element)
            return True
        except:
            return False

    def _handle_popup(self, driver):
        """Menutup pop-up login / iklan yang sering muncul di OLX"""
        self.log("Mengecek popup OLX...")
        try:
            # Tekan Escape untuk mematikan modal/pop-up standar
            webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(1)
            
            # Jika ada tombol silang manual
            close_btns = driver.find_elements(By.CSS_SELECTOR, 'button[data-aut-id="btnClose"]')
            for btn in close_btns:
                if btn.is_displayed():
                    self.safe_click(driver, element=btn)
                    self.log("✅ Pop-up berhasil ditutup.")
                    time.sleep(1)
                    break
        except: pass

    def scrape_olx_logic(self, keyword):
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
            # Akses langsung ke URL dengan filter area Kab. Bantul
            safe_kw = urllib.parse.quote(keyword)
            search_url = f"https://www.olx.co.id/bantul-kab_g4000068/q-{safe_kw}"
            
            self.log(f"Membuka OLX area Bantul untuk: '{keyword}'...")
            driver.get(search_url)
            time.sleep(4)

            self._handle_popup(driver)

            # --- FASE 1: SCROLL & KLIK MUAT LAINNYA ---
            self.log("Menggulir halaman dan memuat semua produk...")
            no_change_count = 0
            last_count = 0
            
            for i in range(30): # Maksimal 30 klik (OLX punya batas load data)
                if self.is_stopped(): break
                
                # Hitung produk saat ini
                current_count = len(driver.find_elements(By.CSS_SELECTOR, 'a[href*="/item/"]'))
                
                # Scroll mentok bawah untuk memicu lazy load
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.5)
                
                load_more_btns = driver.find_elements(By.CSS_SELECTOR, 'button[data-aut-id="btnLoadMore"]')
                if load_more_btns and load_more_btns[0].is_displayed():
                    self.log(f"Klik 'Muat Lainnya' #{i+1}...")
                    self.safe_click(driver, element=load_more_btns[0])
                    time.sleep(3)
                    no_change_count = 0
                else:
                    if current_count == last_count:
                        no_change_count += 1
                        if no_change_count >= 2:
                            self.log("Sudah mentok bawah, tidak ada tombol lagi.")
                            break
                    else:
                        no_change_count = 0
                
                last_count = current_count

            # --- FASE 2: MENGUMPULKAN DATA KARTU ---
            self.log("Mengekstrak URL dari kartu produk...")
            cards = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/item/"]')
            
            items_to_visit = []
            for card in cards:
                if self.is_stopped(): break
                try:
                    url = card.get_attribute("href")
                    if not url: continue
                    if url.startswith("/"): url = "https://www.olx.co.id" + url
                    
                    title_el = card.find_elements(By.CSS_SELECTOR, '[data-aut-id="itemTitle"]')
                    title = clean_text(title_el[0].get_attribute("innerText")) if title_el else ""
                    
                    price_el = card.find_elements(By.CSS_SELECTOR, '[data-aut-id="itemPrice"]')
                    price = clean_text(price_el[0].get_attribute("innerText")) if price_el else ""
                    
                    loc_el = card.find_elements(By.CSS_SELECTOR, '[data-aut-id="item-location"]')
                    location = clean_text(loc_el[0].get_attribute("innerText")) if loc_el else ""
                    
                    if "bantul" not in location.lower(): continue # Filter memastikan lokasi
                    
                    items_to_visit.append({
                        "product_name": title,
                        "price": price,
                        "location": location,
                        "url": url
                    })
                except: pass

            # --- FASE 3: BUKA DETAIL UNTUK NAMA PENJUAL ---
            self.log(f"Membuka detail {len(items_to_visit)} produk untuk mencari identitas penjual...")
            seen_shops = set()
            
            for idx, item in enumerate(items_to_visit):
                if self.is_stopped(): break
                try:
                    driver.get(item["url"])
                    time.sleep(2.5)
                    
                    # Targetkan selector .eHFQs dari hasil inspect Anda
                    seller_els = driver.find_elements(By.CSS_SELECTOR, '.eHFQs, [data-aut-id="profileCard"] ._2tgkn div')
                    seller_name = ""
                    
                    for el in seller_els:
                        if el.is_displayed():
                            seller_name = clean_text(el.get_attribute("innerText"))
                            break
                    
                    if not seller_name or seller_name.lower() == "olx user":
                        # Kalau namanya tidak ketemu, kita ambil sebagian id URL sebagai penanda toko
                        seller_name = f"Penjual OLX - {item['product_name'][:15]}"
                    
                    # Deduplikasi penjual
                    row_key = normalize_name(seller_name)
                    if row_key in seen_shops: continue
                    seen_shops.add(row_key)
                    
                    # Simpan data
                    rows.append({
                        "shop_name": seller_name,
                        "shop_location": item["location"],
                        "product_name": item["product_name"],
                        "price": item["price"],
                        "sold": "N/A" # OLX tidak memiliki fitur "Terjual"
                    })
                    
                    self.log(f"  [{idx+1}/{len(items_to_visit)}] Ditemukan Penjual: {seller_name}")
                except Exception as e:
                    pass
        
        finally:
            driver.quit()
            
        return pd.DataFrame(rows).drop_duplicates(subset=["shop_name"])

    def run(self, keyword):
        df = self.scrape_olx_logic(keyword)
        if df.empty:
            self.log("Tidak ada data ditemukan.")
            return

        self.log(f"Total penjual unik ditemukan: {len(df)}. Memulai pengayaan Google Maps...")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        for i, row in df.iterrows():
            if self.is_stopped(): break
            shop = row["shop_name"]
            
            # Jika namanya "Penjual OLX", kita tidak usah cari di Maps karena tidak relevan
            if "Penjual OLX" in shop:
                status = "DILUAR_RING (Individu)"
                df.at[i, "status"] = status
                self.log(f"Maps: {shop} -> Lewati (Penjual Individu)")
                continue

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

def scrape_olx(keyword, callback=None, stop_check=None):
    scraper = OLXGeoScraper(callback=callback, stop_check=stop_check)
    scraper.run(keyword)