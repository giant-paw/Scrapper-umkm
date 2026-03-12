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

def name_similarity(a, b):
    a, b = normalize_name(a), normalize_name(b)
    if not a or not b: return 0.0
    return round(SequenceMatcher(None, a, b).ratio(), 4)

def classify_match(similarity):
    if similarity >= 0.85: return "TINGGI"
    if similarity >= 0.65: return "SEDANG"
    if similarity >= 0.45: return "RENDAH"
    return "SANGAT_RENDAH"

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

# ================= CLASS UNTUK GUI =================
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
            locator.click(timeout=8000)
            return True
        except:
            try:
                locator.scroll_into_view_if_needed(timeout=3000)
                locator.click(timeout=8000, force=True)
                return True
            except: return False

    def scrape_tokopedia_logic(self, keyword):
        rows = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            
            self.log("Buka Tokopedia...")
            page.goto("https://www.tokopedia.com", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            search_box = page.locator('input[type="search"]').first
            search_box.wait_for(state="visible")
            search_box.fill(keyword)
            search_box.press("Enter")
            page.wait_for_timeout(5000)

            self.log("Filter Kab. Bantul...")
            see_all = page.locator('[data-testid="lnkSRPSeeAllLocFilter"]').first
            if not self.safe_click(see_all): return pd.DataFrame()

            lokasi_input = page.locator('input[aria-label="Cari lokasi"]').first
            lokasi_input.fill("Kab. Bantul")
            page.wait_for_timeout(2500)

            target = page.locator('xpath=//*[contains(normalize-space(text()),"Kab. Bantul")]/ancestor::*[self::label or self::div or self::li][1]').first
            self.safe_click(target)
            self.safe_click(page.locator('[data-testid="btnSRPApplySeeAllFilter"]').first)
            page.wait_for_timeout(5000)

            # Load More Logic
            for i in range(200):
                if self.is_stopped(): break
                btn = page.locator('button:has-text("Muat Lebih Banyak")').first
                if btn.count() > 0 and btn.is_visible():
                    self.log(f"Klik Muat Lebih Banyak #{i+1}")
                    if not self.safe_click(btn): break
                    page.wait_for_timeout(2500)
                else: break

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

                    row_key = (normalize_name(parsed["shop_name"]), normalize_name(parsed["product_name"]))
                    if row_key in seen_cards: continue
                    seen_cards.add(row_key)

                    rows.append({
                        "shop_name": parsed["shop_name"],
                        "shop_location": parsed["shop_location"],
                        "product_name": parsed["product_name"],
                        "price": parsed["price"],
                        "sold": parsed["sold"]
                    })
                    self.log(f"Ditemukan: {parsed['shop_name']}")
                except: pass
            browser.close()
        return pd.DataFrame(rows).drop_duplicates(subset=["shop_name"])

    def run(self, keyword):
        df = self.scrape_tokopedia_logic(keyword)
        if df.empty:
            self.log("Tidak ada data ditemukan.")
            return

        self.log("Memulai pengayaan Google Maps...")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless") # Headless agar lebih cepat di GUI
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        for i, row in df.iterrows():
            if self.is_stopped(): break
            shop = row["shop_name"]
            driver.get("https://www.google.com/maps/search/" + urllib.parse.quote(f"{shop}, {CTX}"))
            time.sleep(4)

            m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+),", driver.current_url)
            lat, lng = (float(m.group(1)), float(m.group(2))) if m else (None, None)
            
            geo_info = self.find_geojson_match(lat, lng)
            status = "DALAM_RING" if geo_info else "DILUAR_RING"
            
            df.at[i, "latitude"] = lat
            df.at[i, "longitude"] = lng
            df.at[i, "idsls"] = geo_info["idsls"] if geo_info else ""
            df.at[i, "status"] = status
            
            self.log(f"Maps: {shop} -> {status}")

        driver.quit()
        output_file = f"{OUTPUT_PREFIX}_{sanitize_filename(keyword)}_enriched.xlsx"
        df.to_excel(output_file, index=False)
        self.log(f"Selesai! File: {output_file}")

def scrape_tokopedia(keyword, callback=None, stop_check=None):
    scraper = TokopediaGeoScraper(callback=callback, stop_check=stop_check)
    scraper.run(keyword)