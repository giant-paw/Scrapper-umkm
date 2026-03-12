import time
import re
import json
import urllib.parse
from difflib import SequenceMatcher
import pandas as pd
import requests

from playwright.sync_api import sync_playwright
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

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

    def safe_click(self, locator):
        try:
            locator.scroll_into_view_if_needed(timeout=3000)
            locator.click(timeout=8000, force=True)
            return True
        except: return False

    def scroll_and_load_more(self, page, max_rounds=50):
        self.log("Memulai simulasi scroll ke bawah untuk memuat produk...")
        
        last_item_count = 0
        no_change_count = 0
        
        for i in range(max_rounds):
            if self.is_stopped(): break
            
            # 1. Hitung jumlah produk yang ada di layar saat ini
            current_item_count = page.locator('img[alt="product-image"]').count()
            
            # 2. Evaluasi apakah ada penambahan produk baru
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
            
            # 3. Scroll perlahan ke bawah
            for _ in range(3):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(800)
                
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            
            # 4. Cari dan klik tombol
            btn = page.locator('button:has-text("Muat Lebih Banyak")').first
            
            if btn.count() > 0 and btn.is_visible():
                self.log(f"Klik 'Muat Lebih Banyak' #{i+1}")
                self.safe_click(btn)
                page.wait_for_timeout(3500)

    def scrape_tokopedia_logic(self, keyword):
        rows = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            
            self.log(f"Mencari produk: {keyword}")
            page.goto("https://www.tokopedia.com", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            search_box = page.locator('input[type="search"]').first
            search_box.fill(keyword)
            search_box.press("Enter")
            page.wait_for_timeout(5000)

            self.log("Menerapkan Filter Lokasi (Kab. Bantul)...")
            see_all = page.locator('[data-testid="lnkSRPSeeAllLocFilter"]').first
            if not self.safe_click(see_all): 
                browser.close()
                return pd.DataFrame()

            page.locator('input[aria-label="Cari lokasi"]').first.fill("Kab. Bantul")
            page.wait_for_timeout(2000)
            
            target = page.locator('xpath=//*[contains(normalize-space(text()),"Kab. Bantul")]/ancestor::*[self::label or self::div or self::li][1]').first
            self.safe_click(target)
            self.safe_click(page.locator('[data-testid="btnSRPApplySeeAllFilter"]').first)
            page.wait_for_timeout(5000)

            # --- EKSEKUSI SCROLL DAN KLIK MENTOK ---
            self.scroll_and_load_more(page)

            self.log("Scraping semua data yang sudah terbuka...")
            product_imgs = page.locator('img[alt="product-image"]')
            seen_cards = set()
            
            for i in range(product_imgs.count()):
                if self.is_stopped(): break
                try:
                    img = product_imgs.nth(i)
                    card = img.locator("xpath=ancestor::div[contains(., 'Kab. Bantul')][1]")
                    if card.count() == 0: continue

                    texts = card.locator("span").all_inner_texts()
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
            browser.close()
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