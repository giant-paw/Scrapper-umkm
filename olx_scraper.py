import os
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
CTX = "Bantul" # Untuk filter URL awal
MAPS_CTX = "Yogyakarta" # Khusus untuk pencarian di Maps
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
        try:
            with open(GEOJSON_FILE, "r", encoding="utf-8") as f:
                self.gj = json.load(f)
        except Exception as e:
            self.log(f"Peringatan: Gagal memuat {GEOJSON_FILE}: {e}")
            self.gj = {}

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

    def _handle_popup(self, driver):
        self.log("Mengecek popup OLX...")
        try:
            webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(1)
            
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
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        try:
            safe_kw = urllib.parse.quote(keyword)
            # Pencarian default sudah menggunakan kode area Bantul
            search_url = f"https://www.olx.co.id/bantul-kab_g4000068/q-{safe_kw}"
            
            self.log(f"Membuka OLX area Bantul untuk: '{keyword}'...")
            driver.get(search_url)
            time.sleep(4)

            self._handle_popup(driver)

            self.log("Menggulir halaman dan memuat semua produk...")
            no_change_count = 0
            last_count = 0
            
            for i in range(30):
                if self.is_stopped(): break
                
                current_count = len(driver.find_elements(By.CSS_SELECTOR, 'a[href*="/item/"]'))
                
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

            self.log("Mengekstrak URL dari kartu produk...")
            
            # Selector diganti ke parent 'li' agar lebih kuat mengekstrak info
            cards = driver.find_elements(By.CSS_SELECTOR, 'li[data-aut-id="itemBox"], a[href*="/item/"]')
            
            items_to_visit = []
            seen_urls = set()
            
            for card in cards:
                if self.is_stopped(): break
                try:
                    # Cari URL
                    if card.tag_name == "a":
                        url = card.get_attribute("href")
                    else:
                        link_el = card.find_elements(By.CSS_SELECTOR, 'a[href*="/item/"]')
                        url = link_el[0].get_attribute("href") if link_el else ""
                        
                    if not url or url in seen_urls: continue
                    seen_urls.add(url)
                    if url.startswith("/"): url = "https://www.olx.co.id" + url

                    # Ambil informasi teks card secara cerdas
                    card_text = card.get_attribute("innerText") or ""
                    lines = [line.strip() for line in card_text.split('\n') if line.strip()]
                    
                    title = ""
                    price = ""
                    location = ""
                    
                    for line in lines:
                        if line.startswith("Rp"): price = line
                        elif not title and len(line) > 4 and "Rp" not in line: title = line
                        
                    loc_el = card.find_elements(By.CSS_SELECTOR, '[data-aut-id="item-location"]')
                    if loc_el:
                        location = clean_text(loc_el[0].get_attribute("innerText"))
                    elif len(lines) >= 3:
                        location = lines[-1]

                    # FILTER STRING "BANTUL" DIHAPUS agar kecamatan (misal Sewon) tidak dibuang!
                    items_to_visit.append({
                        "product_name": title or "Produk OLX",
                        "price": price or "N/A",
                        "location": location or "Bantul",
                        "url": url
                    })
                except: pass

            self.log(f"Membuka detail {len(items_to_visit)} produk untuk mencari identitas penjual...")
            seen_shops = set()
            
            for idx, item in enumerate(items_to_visit):
                if self.is_stopped(): break
                try:
                    driver.get(item["url"])
                    time.sleep(2.5)
                    
                    # Selector untuk menangkap nama
                    seller_els = driver.find_elements(By.CSS_SELECTOR, '.eHFQs, [data-aut-id="profileCard"] ._2tgkn div, [data-aut-id="profileCard"] span')
                    seller_name = ""
                    
                    for el in seller_els:
                        if el.is_displayed():
                            txt = clean_text(el.get_attribute("innerText"))
                            # Abaikan jika tulisannya cuma "OLX User" atau deskripsi tgl bergabung
                            if txt and txt.lower() != "olx user" and "member sejak" not in txt.lower():
                                seller_name = txt
                                break
                    
                    # PERBAIKAN: Jika tetap kosong, gunakan ID IKLAN dari URL agar TIDAK TERTUMPUK
                    if not seller_name or seller_name.lower() == "olx user":
                        item_id = item["url"].split("-iid-")[-1] if "-iid-" in item["url"] else str(idx)
                        seller_name = f"Penjual Individu {item_id}"
                    
                    # Deduplikasi penjual berdasarkan namanya
                    row_key = normalize_name(seller_name)
                    if row_key in seen_shops: continue
                    seen_shops.add(row_key)
                    
                    # Simpan data
                    rows.append({
                        "shop_name": seller_name,
                        "shop_location": item["location"],
                        "product_name": item["product_name"],
                        "price": item["price"],
                        "sold": "N/A"
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
        # options.add_argument("--headless") # Maps Tampil di Layar
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        final_rows = []

        for i, row in df.iterrows():
            if self.is_stopped(): break
            shop = row["shop_name"]
            
            maps_query = f"{shop} {MAPS_CTX}"
            maps_place_name, maps_address, phone, maps_url = "", "", "", ""
            lat, lng = None, None
            geo_info = None
            similarity = 0.0
            match_quality = "RENDAH"

            # Lewati Map untuk penjual individu yang tak ber-identitas pasti
            if "Penjual Individu" in shop:
                status = "DILUAR_RING (Individu)"
                self.log(f"Maps: {shop} -> Lewati (Penjual Individu)")
            else:
                self.log(f"Mencari di Maps: {maps_query}")
                driver.get("https://www.google.com/maps/search/" + urllib.parse.quote(maps_query))
                time.sleep(4)
                
                try:
                    place_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/place/"]')
                    if place_links:
                        driver.execute_script("arguments[0].click();", place_links[0])
                        time.sleep(3)
                except: pass

                maps_url = driver.current_url
                
                try:
                    h1 = driver.find_element(By.CSS_SELECTOR, "h1")
                    maps_place_name = clean_text(h1.text)
                except: 
                    maps_place_name = shop

                try:
                    btn_addr = driver.find_element(By.CSS_SELECTOR, 'button[data-item-id="address"]')
                    maps_address = btn_addr.get_attribute("aria-label").replace("Alamat: ", "").strip()
                    if not maps_address:
                        maps_address = clean_text(btn_addr.text)
                except: pass

                try:
                    btn_phone = driver.find_element(By.CSS_SELECTOR, 'button[data-item-id^="phone:tel:"]')
                    phone = btn_phone.get_attribute("aria-label").replace("Nomor telepon: ", "").strip()
                    if not phone:
                        phone = clean_text(btn_phone.text)
                except: pass

                m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+),", maps_url)
                lat, lng = (float(m.group(1)), float(m.group(2))) if m else (None, None)
                
                geo_info = self.find_geojson_match(lat, lng)
                
                if lat is None:
                    status = "NOT_FOUND"
                else:
                    status = "DALAM_RING" if geo_info else "DILUAR_RING"
                
                similarity = SequenceMatcher(None, shop.lower(), maps_place_name.lower()).ratio()
                if similarity >= 0.8:
                    match_quality = "TINGGI"
                elif similarity >= 0.5:
                    match_quality = "SEDANG"
                else:
                    match_quality = "RENDAH"

                self.log(f"Maps: {shop} -> {status} | Sim: {round(similarity, 2)} | Telp: {phone}")

            # Array 17 Kolom
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
                "website": "",  # Blank
                "email": "",    # Blank
                "maps_url": maps_url,
                "idsls": geo_info["idsls"] if geo_info else "",                 
                "nama_kecamatan": geo_info["nama_kecamatan"] if geo_info else "", 
                "nama_desa": geo_info["nama_desa"] if geo_info else "",           
                "nama_sls": geo_info["nama_sls"] if geo_info else "",             
                "status": status                                                
            })

        driver.quit()
        
        output_df = pd.DataFrame(final_rows, columns=[
            "shop_name", "maps_query", "maps_place_name", "maps_address", 
            "name_similarity", "match_quality", "latitude", "longitude", 
            "phone", "website", "email", "maps_url", 
            "idsls", "nama_kecamatan", "nama_desa", "nama_sls", "status"
        ])

        if not os.path.exists("data"):
            os.makedirs("data")
        
        output_file = "{sanitize_filename(keyword)}_{OUTPUT_PREFIX}_enriched.xlsx"
        output_df.to_excel(output_file, index=False)
        self.log(f"✅ Selesai! File disimpan: {output_file}")

def scrape_olx(keyword, callback=None, stop_check=None):
    scraper = OLXGeoScraper(callback=callback, stop_check=stop_check)
    scraper.run(keyword)