import time
import re
import urllib.parse
from difflib import SequenceMatcher
import pandas as pd
import requests

import geopandas as gpd
from shapely.geometry import Point

from playwright.sync_api import sync_playwright
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= CONFIG =================
GEOJSON_FILE = "bantul.geojson"  
CTX = "Bantul"
OUTPUT_PREFIX = "shopee"

# ================= UTILITY FUNCTIONS =================
def sanitize_filename(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_") or "output"

def normalize_name(text: str) -> str:
    if not text: return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def name_similarity(a: str, b: str) -> float:
    a, b = normalize_name(a), normalize_name(b)
    if not a or not b: return 0.0
    return round(SequenceMatcher(None, a, b).ratio(), 4)

def classify_match(similarity: float) -> str:
    if similarity >= 0.85: return "TINGGI"
    if similarity >= 0.65: return "SEDANG"
    if similarity >= 0.45: return "RENDAH"
    return "SANGAT_RENDAH"

# ================= MAPS EXTRACTOR HELPERS =================
def extract_phone(driver) -> str:
    try:
        el = driver.find_element(By.CSS_SELECTOR, 'button[data-item-id^="phone"]')
        return el.text
    except Exception: return ""

def extract_website(driver) -> str:
    try:
        el = driver.find_element(By.CSS_SELECTOR, 'a[data-item-id="authority"]')
        return el.get_attribute("href")
    except Exception: return ""

def extract_maps_place_name(driver) -> str:
    selectors = ["h1", 'h1[class]', 'div[role="main"] h1']
    for sel in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text: return text
        except Exception: pass
    return ""

def extract_email(url: str) -> str:
    if not url: return ""
    try:
        r = requests.get(url, timeout=5)
        emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}", r.text)
        if emails: return emails[0]
    except Exception: pass
    return ""

# ================= MAIN SCRAPER CLASS =================
class ShopeeGeoScraper:
    def __init__(self, callback=None, stop_check=None):
        self.log_callback = callback
        self.stop_check = stop_check
        self.gdf_peta = self._load_geojson_fast()

    def log(self, *args):
        msg = " ".join(map(str, args))
        print(msg) 
        if self.log_callback:
            self.log_callback(msg)

    def is_stopped(self) -> bool:
        return self.stop_check() if self.stop_check else False

    def _load_geojson_fast(self):
        try:
            return gpd.read_file(GEOJSON_FILE)
        except Exception as e:
            self.log(f"⚠️ WARNING: Gagal memuat peta {GEOJSON_FILE}. Error: {e}")
            return None

    def find_geojson_match(self, lat: float, lng: float) -> dict | None:
        if lat is None or lng is None or self.gdf_peta is None: return None
        titik = Point(lng, lat)
        match = self.gdf_peta[self.gdf_peta.geometry.contains(titik)]
        
        if not match.empty:
            baris = match.iloc[0]
            return {
                "idsls": str(baris.get("idsls", "")), 
                "nama_kabupaten": str(baris.get("nmkab", "")), 
                "nama_kecamatan": str(baris.get("nmkec", "")), 
                "nama_desa": str(baris.get("nmdesa", "")), 
                "nama_sls": str(baris.get("nmsls", ""))
            }
        return None

    def extract_shopee_shops(self, keyword: str) -> pd.DataFrame:
        shops = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, channel="msedge")
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            try:
                self.log("Membuka Shopee (Harap tunggu jika ada loading/captcha)...")
                # Menggunakan pencarian berbasis produk langsung karena tab Toko kadang disembunyikan
                search_url = f"https://shopee.co.id/search?keyword={urllib.parse.quote(keyword)}"
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                
                # Memberi jeda ekstra untuk Shopee loading scriptnya (seringkali berat)
                page.wait_for_timeout(5000)
                
                # Tutup popup bahasa/promo jika muncul
                try: page.keyboard.press("Escape")
                except Exception: pass

                # Coba cari filter lokasi "Bantul" jika tersedia di sidebar
                self.log("Mencoba filter lokasi (Kab. Bantul)...")
                try:
                    # Shopee sidebar lokasi (ini sangat dinamis, kita lakukan best-effort)
                    more_location_btn = page.locator('div:has-text("Lainnya")').nth(0)
                    if more_location_btn.is_visible():
                        more_location_btn.click()
                        page.wait_for_timeout(1000)
                    
                    bantul_checkbox = page.locator('label:has-text("Bantul")').first
                    if bantul_checkbox.is_visible():
                        bantul_checkbox.click()
                        page.wait_for_timeout(3000)
                except Exception:
                    self.log("Filter lokasi Bantul tidak ditemukan. Scraping area general.")

                page_count = 1
                while True:
                    if self.is_stopped(): break
                    self.log(f"Ekstraksi halaman {page_count}...")
                    
                    # Scroll perlahan ke bawah untuk meload item (Shopee menggunakan lazy loading)
                    for _ in range(5):
                        page.mouse.wheel(0, 800)
                        page.wait_for_timeout(1000)

                    # Ambil semua produk yang muncul
                    items = page.locator('div[data-sqe="item"]')
                    count = items.count()
                    
                    if count == 0: 
                        self.log("Tidak ada produk/toko ditemukan lagi.")
                        break

                    for i in range(count):
                        if self.is_stopped(): break
                        try:
                            # Pada hasil pencarian Shopee, info lokasi sering tertera di bawah produk
                            lokasi = items.nth(i).locator('div[data-sqe="name"] ~ div').last.inner_text()
                            
                            # Filter lokal via kode jika filter UI gagal (Opsional tapi membantu akurasi)
                            if "Bantul" in lokasi or "DI Yogyakarta" in lokasi:
                                # Jika kita masuk ke produk untuk mengambil nama tokonya (karena di hal depan hanya produk)
                                # Shopee agak rumit, nama toko tidak selalu ada di halaman pencarian
                                # Sebagai solusi cepat: Ambil URL produk, anggap url-nya mengandung username toko
                                prod_url = items.nth(i).locator('a').first.get_attribute("href")
                                if prod_url:
                                    # Format URL Shopee: /Nama-Produk-i.shop_id.item_id
                                    # Atau kita potong nama produknya saja sebagai representasi sementara
                                    parts = prod_url.split("-i.")
                                    if len(parts) == 2:
                                        shop_info = parts[0].replace("/", "")
                                        # Bersihkan string untuk jadi nama
                                        clean_name = shop_info.replace("-", " ").title()[:30] 
                                        shops.append({"shop_name": f"Toko {clean_name}", "shop_url": "https://shopee.co.id" + prod_url})
                                        self.log(f"SHOPEE DETECTED: Toko {clean_name} (Area: {lokasi})")
                        except Exception:
                            continue

                    # Cek tombol Next
                    next_btn = page.locator('button.shopee-icon-button.shopee-icon-button--right').first
                    if next_btn.count() == 0 or next_btn.get_attribute("disabled") is not None:
                        break
                    
                    try:
                        next_btn.click()
                        page.wait_for_timeout(3000)
                        page_count += 1
                        if page_count > 3: # Batasi 3 halaman saja agar tidak kena blokir Cloudflare
                            self.log("Batas aman 3 halaman Shopee tercapai.")
                            break
                    except Exception:
                        break

            finally:
                browser.close()

        df = pd.DataFrame(shops)
        return df.drop_duplicates(subset=["shop_name"]) if not df.empty else df

    def enrich_google_maps(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df
        
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        prefs = {"profile.managed_default_content_settings.images": 2} 
        options.add_experimental_option("prefs", prefs)
        
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        columns_to_add = [
            "maps_place_name", "name_similarity", "match_quality", "inside_ring", 
            "status", "idsls", "nama_kabupaten", "nama_kecamatan", "nama_desa", 
            "nama_sls", "latitude", "longitude", "phone", "website", "email", "maps_url"
        ]
        for col in columns_to_add: df[col] = None

        try:
            for i, row in df.iterrows():
                if self.is_stopped(): break 

                shop = row["shop_name"]
                query = f"{shop}, {CTX}"
                url = "https://www.google.com/maps/search/" + urllib.parse.quote(query)
                driver.get(url)

                try:
                    place_links = WebDriverWait(driver, 4).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'a[href*="/place/"]'))
                    )
                    if place_links: place_links[0].click()
                except Exception: pass

                lat, lng = None, None
                for _ in range(8):
                    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+),", driver.current_url)
                    if m:
                        lat, lng = float(m.group(1)), float(m.group(2))
                        break
                    time.sleep(0.5)
                
                maps_place_name = extract_maps_place_name(driver)
                similarity = name_similarity(shop, maps_place_name)
                match_quality = classify_match(similarity)
                
                phone = extract_phone(driver)
                website = extract_website(driver)
                email = extract_email(website)

                geo_info = self.find_geojson_match(lat, lng)
                inside_ring = geo_info is not None
                status = "DALAM_RING" if inside_ring else "DILUAR_RING"

                df.at[i, "maps_place_name"] = maps_place_name
                df.at[i, "name_similarity"] = similarity
                df.at[i, "match_quality"] = match_quality
                df.at[i, "inside_ring"] = inside_ring
                df.at[i, "status"] = status
                
                if geo_info:
                    df.at[i, "idsls"] = geo_info.get("idsls", "")
                    df.at[i, "nama_kabupaten"] = geo_info.get("nama_kabupaten", "")
                    df.at[i, "nama_kecamatan"] = geo_info.get("nama_kecamatan", "")
                    df.at[i, "nama_desa"] = geo_info.get("nama_desa", "")
                    df.at[i, "nama_sls"] = geo_info.get("nama_sls", "")
                
                df.at[i, "latitude"] = lat
                df.at[i, "longitude"] = lng
                df.at[i, "phone"] = phone
                df.at[i, "website"] = website
                df.at[i, "email"] = email
                df.at[i, "maps_url"] = driver.current_url
                
                self.log(f"MAPS: {shop} | sim: {similarity} | {status}")

        finally:
            driver.quit()
        return df

    def run(self, keyword: str):
        self.log(f"--- Memulai Ekstraksi Shopee untuk: {keyword} ---")
        df = self.extract_shopee_shops(keyword)
        if self.is_stopped() or len(df) == 0: return 
        
        self.log(f"\nTotal toko terdeteksi: {len(df)}")
        self.log("\n--- Memulai Pencarian Google Maps ---")
        df = self.enrich_google_maps(df)

        output_file = f"{OUTPUT_PREFIX}_{sanitize_filename(keyword)}_bantul_enriched.xlsx"
        df.to_excel(output_file, index=False)
        self.log(f"\n✅ Data disimpan di: {output_file}")

# ================= ENTRY POINT UNTUK GUI =================
def scrape_shopee(keyword, callback=None, stop_check=None):
    if not keyword: return
    scraper = ShopeeGeoScraper(callback=callback, stop_check=stop_check)
    scraper.run(keyword)