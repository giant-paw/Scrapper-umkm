import time
import re
import urllib.parse
from difflib import SequenceMatcher
import pandas as pd
import requests

# Tambahan untuk geospasial yang jauh lebih cepat
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
GEOJSON_FILE = "bantul.geojson"  # Pastikan nama file geojson sudah benar
CTX = "Bantul"
OUTPUT_PREFIX = "tokopedia"

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
    except Exception:
        return ""

def extract_website(driver) -> str:
    try:
        el = driver.find_element(By.CSS_SELECTOR, 'a[data-item-id="authority"]')
        return el.get_attribute("href")
    except Exception:
        return ""

def extract_maps_place_name(driver) -> str:
    selectors = ["h1", 'h1[class]', 'div[role="main"] h1']
    for sel in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text: return text
        except Exception:
            pass
    return ""

def extract_email(url: str) -> str:
    if not url: return ""
    try:
        r = requests.get(url, timeout=8)
        emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}", r.text)
        if emails: return emails[0]
    except Exception:
        pass
    return ""

# ================= MAIN SCRAPER CLASS =================
class TokopediaGeoScraper:
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
        if lat is None or lng is None or self.gdf_peta is None: 
            return None
        
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

    def safe_click(self, locator) -> bool:
        try:
            locator.wait_for(state="visible", timeout=8000)
            locator.click()
            return True
        except Exception:
            try:
                locator.scroll_into_view_if_needed(timeout=3000)
                locator.click(force=True)
                return True
            except Exception:
                return False

    def extract_tokopedia_shops(self, keyword: str) -> pd.DataFrame:
        shops = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, channel="msedge")
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            try:
                self.log("Buka Tokopedia...")
                page.goto("https://www.tokopedia.com", wait_until="domcontentloaded", timeout=60000)
                
                try: page.keyboard.press("Escape")
                except Exception: pass

                search_box = page.locator('input[type="search"]').first
                search_box.wait_for(state="visible", timeout=15000)
                search_box.click()
                search_box.fill(keyword)
                search_box.press("Enter")
                
                try:
                    page.locator('[data-testid="btnSRPShopTab"]').first.wait_for(state="visible", timeout=10000)
                except Exception:
                    self.log("Tab Toko tidak ditemukan")
                    return pd.DataFrame(columns=["shop_name", "shop_url"])

                self.log("Klik tab Toko...")
                shop_tab = page.locator('[data-testid="btnSRPShopTab"]').first
                if not self.safe_click(shop_tab): 
                    return pd.DataFrame(columns=["shop_name", "shop_url"])

                self.log("Menerapkan Filter Lokasi...")
                see_all_loc = page.locator('[data-testid="lnkSRPSeeAllLocFilter"]').first
                if self.safe_click(see_all_loc):
                    lokasi_input = page.locator('input[aria-label="Cari lokasi"]').first
                    lokasi_input.wait_for(state="visible", timeout=5000)
                    lokasi_input.click()
                    lokasi_input.fill("Kab. Bantul")
                    
                    target_checkbox = page.locator('xpath=//*[normalize-space(text())="Kab. Bantul"]/ancestor::*[self::label or self::div or self::li][1]//*[contains(@class,"checkbox__area")]').first
                    if self.safe_click(target_checkbox):
                        apply_btn = page.locator('[data-testid="btnSRPApplySeeAllFilter"]').first
                        self.safe_click(apply_btn)
                        page.wait_for_timeout(3000)

                page_count = 1
                while True:
                    if self.is_stopped():
                        self.log("🛑 Scraping web Tokopedia dihentikan.")
                        break

                    self.log(f"Ekstraksi halaman {page_count}...")
                    
                    try:
                        page.locator('div[data-testid="shop-card"]').first.wait_for(state="visible", timeout=5000)
                    except Exception:
                        pass 
                        
                    cards = page.locator('div[data-testid="shop-card"]')
                    count = cards.count()
                    if count == 0: break

                    for i in range(count):
                        try: 
                            name = cards.nth(i).locator('[data-testid="spnSRPShopName"]').inner_text(timeout=2000).strip()
                            url = cards.nth(i).locator('a[data-testid="shop-card-header"]').get_attribute("href", timeout=2000)
                            if name: 
                                shops.append({"shop_name": name, "shop_url": url})
                                self.log(f"TOKOPEDIA: {name}")
                        except Exception: 
                            continue

                    next_btn = page.locator('[aria-label="Laman berikutnya"]').first
                    try:
                        if next_btn.count() == 0 or next_btn.get_attribute("disabled") is not None or next_btn.get_attribute("aria-disabled") == "true": 
                            break
                    except Exception: 
                        break

                    if not self.safe_click(next_btn): break
                    page.wait_for_timeout(2500)
                    page_count += 1

            finally:
                browser.close()

        df = pd.DataFrame(shops)
        return df.drop_duplicates(subset=["shop_name"]) if not df.empty else df

    def enrich_google_maps(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df
        
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        prefs = {"profile.managed_default_content_settings.images": 2} # Blokir gambar untuk kecepatan
        options.add_experimental_option("prefs", prefs)
        
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        # Inisialisasi Kolom Baru Sesuai Kode Acuan
        columns_to_add = [
            "maps_place_name", "name_similarity", "match_quality", "inside_ring", 
            "status", "idsls", "nama_kabupaten", "nama_kecamatan", "nama_desa", 
            "nama_sls", "latitude", "longitude", "phone", "website", "email", "maps_url"
        ]
        for col in columns_to_add:
            df[col] = None

        try:
            for i, row in df.iterrows():
                if self.is_stopped(): 
                    self.log("🛑 Pencarian Google Maps dihentikan.")
                    break 

                shop = row["shop_name"]
                query = f"{shop}, {CTX}"
                url = "https://www.google.com/maps/search/" + urllib.parse.quote(query)
                driver.get(url)

                try:
                    place_links = WebDriverWait(driver, 4).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'a[href*="/place/"]'))
                    )
                    if place_links: 
                        place_links[0].click()
                except Exception: 
                    pass

                # Tunggu map load & ambil koordinat
                lat, lng = None, None
                for _ in range(8):
                    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+),", driver.current_url)
                    if m:
                        lat, lng = float(m.group(1)), float(m.group(2))
                        break
                    time.sleep(0.5)
                
                # Ekstraksi Data Tambahan
                maps_place_name = extract_maps_place_name(driver)
                similarity = name_similarity(shop, maps_place_name)
                match_quality = classify_match(similarity)
                
                phone = extract_phone(driver)
                website = extract_website(driver)
                email = extract_email(website)

                # Cek Spasial Geopandas
                geo_info = self.find_geojson_match(lat, lng)
                inside_ring = geo_info is not None
                status = "DALAM_RING" if inside_ring else "DILUAR_RING"

                # Update DataFrame
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
                
                self.log(f"MAPS: {shop} | {maps_place_name} | sim: {similarity} | {status} | IDSLS: {geo_info['idsls'] if geo_info else '-'}")

        finally:
            driver.quit()
            
        return df

    def run(self, keyword: str):
        self.log(f"--- Memulai Ekstraksi Tokopedia untuk: {keyword} ---")
        df = self.extract_tokopedia_shops(keyword)
        
        if self.is_stopped() and len(df) == 0:
            return 
            
        self.log(f"\nTotal toko unik yang ditemukan: {len(df)}")
        if len(df) == 0: return

        if not self.is_stopped():
            self.log("\n--- Memulai Pencarian Google Maps ---")
            df = self.enrich_google_maps(df)

        output_file = f"{OUTPUT_PREFIX}_{sanitize_filename(keyword)}_bantul_enriched.xlsx"
        df.to_excel(output_file, index=False)
        self.log(f"\n✅ Data berhasil disimpan di: {output_file}")


# ================= ENTRY POINT UNTUK GUI =================
def scrape_tokopedia(keyword, callback=None, stop_check=None):
    if not keyword: return
    scraper = TokopediaGeoScraper(callback=callback, stop_check=stop_check)
    scraper.run(keyword)

# Bisa dieksekusi langsung tanpa GUI dengan menambahkan script ini di bawah:
if __name__ == "__main__":
    keyword_input = input("Keyword Tokopedia: ").strip()
    if keyword_input:
        scrape_tokopedia(keyword_input)
    else:
        print("Keyword tidak boleh kosong")