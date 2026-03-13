import time
import re
import json
import urllib.parse
from difflib import SequenceMatcher
import pandas as pd

from playwright.sync_api import sync_playwright
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

# ================= CONFIG & UTILITY =================
GEOJSON_FILE = "bantul.geojson"
CTX = "Bantul"
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
        # Memuat GeoJSON manual (sama seperti Tokopedia)
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

    def _handle_location_popup(self, page):
        self.log("Mengecek popup lokasi Blibli...")
        try:
            nanti_btn = page.locator("button.blu-button").filter(has_text=re.compile(r"Nanti saja", re.IGNORECASE)).first
            if nanti_btn.is_visible(timeout=3000):
                self.safe_click(nanti_btn)
                page.wait_for_timeout(1000)
        except: pass

    def _apply_filter(self, page):
        self.log("Menerapkan filter Lokasi (Kab. Bantul)...")
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
                    self.safe_click(lihat_semua)
                    modal = page.locator("div.filter-desktop-modal").first
                    modal.wait_for(state="visible", timeout=3000)
                    
                    checkbox_label = modal.locator("label.blu-checkbox").filter(has_text=re.compile(r"^Kab. Bantul$", re.IGNORECASE)).first
                    if checkbox_label.is_visible():
                        self.safe_click(checkbox_label)
                        page.wait_for_timeout(500)
                    else:
                        search_input = modal.locator("input.blu-text-field").first
                        if search_input.is_visible():
                            search_input.fill("Kab. Bantul")
                            page.wait_for_timeout(2000)
                            checkbox_label = modal.locator("label.blu-checkbox").filter(has_text=re.compile(r"^Kab. Bantul$", re.IGNORECASE)).first
                            if checkbox_label.is_visible():
                                self.safe_click(checkbox_label)
                                page.wait_for_timeout(500)

                    simpan_btn = modal.locator("button").filter(has_text=re.compile(r"Simpan", re.IGNORECASE)).first
                    if simpan_btn.is_visible() and not simpan_btn.is_disabled():
                        self.safe_click(simpan_btn)
                        self.log("Filter Kab. Bantul BERHASIL diterapkan.")
                        page.wait_for_timeout(4000)
                        return True
                else:
                    direct_check = target_group.locator("label").filter(has_text="Kab. Bantul").first
                    if direct_check.is_visible():
                        self.safe_click(direct_check)
                        self.log("Filter Kab. Bantul (Langsung) BERHASIL diterapkan.")
                        page.wait_for_timeout(4000)
                        return True
        except Exception as e:
            self.log(f"Gagal menerapkan filter otomatis: {e}")
        return False

    def scrape_blibli_logic(self, keyword):
        rows = []
        with sync_playwright() as p:
            # SENJATA ANTI-BOT DIKEMBALIKAN DI SINI
            browser = p.chromium.launch(
                headless=False, 
                channel="msedge", 
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(no_viewport=True) 
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get:()=>undefined})")
            page = context.new_page()
            
            self.log(f"Mencari produk di Blibli: {keyword}")
            page.goto("https://www.blibli.com/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            inp = page.locator("input[placeholder*='Cari'], input[type='search'], input[data-testid*='search']").first
            if inp.is_visible():
                inp.click()
                inp.fill(keyword)
                page.keyboard.press("Enter")
                page.wait_for_timeout(4000)
            else:
                self.log("⚠️ Kolom pencarian terblokir atau tidak ditemukan.")
                browser.close()
                return pd.DataFrame()

            self._handle_location_popup(page)
            
            for _ in range(3):
                if self.is_stopped(): break
                if self._apply_filter(page): break

            seen_shops = set()
            current_page = 1
            max_pages = 10

            while current_page <= max_pages:
                if self.is_stopped(): break

                self.log(f"\n--- Memproses Halaman {current_page} ---")
                
                # Simulasi scroll ke bawah perlahan ala Tokopedia
                self.log("Simulasi scroll ke bawah untuk memuat item...")
                for _ in range(5):
                    page.mouse.wheel(0, 1000)
                    page.wait_for_timeout(800)
                
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

                product_cards = page.locator("div.product-list__card").all()
                self.log(f"Mengekstrak {len(product_cards)} produk di halaman ini...")
                
                for idx, card in enumerate(product_cards):
                    if self.is_stopped(): break
                    try:
                        product_name_elem = card.locator("span.els-product__title").first
                        product_name = clean_text(product_name_elem.text_content()) if product_name_elem.count() > 0 else ""
                        
                        shop_elem = card.locator("span.els-product__seller-name").first
                        shop_name = clean_text(shop_elem.text_content()) if shop_elem.count() > 0 else ""
                        
                        if not shop_name or shop_name in seen_shops: continue
                        seen_shops.add(shop_name)
                        
                        price_elem = card.locator("div.els-product__fixed-price span").last
                        price = "Rp " + clean_text(price_elem.text_content()) if price_elem.count() > 0 else ""
                        
                        sold_elem = card.locator("div.els-product__sold").first
                        sold = clean_text(sold_elem.text_content()) if sold_elem.count() > 0 else ""
                        
                        if product_name:
                            # Disamakan format kolomnya dengan Tokopedia
                            rows.append({
                                "shop_name": shop_name,
                                "shop_location": "Kab. Bantul",
                                "product_name": product_name,
                                "price": price,
                                "sold": sold
                            })
                            self.log(f"Ditemukan: {shop_name}")
                    except: pass
                
                if current_page < max_pages and not self.is_stopped():
                    try:
                        next_page_btn = page.locator("button.blu-pagination__button").filter(has_text=str(current_page + 1)).first
                        if next_page_btn.is_visible():
                            self.log(f"Pindah ke halaman {current_page + 1}...")
                            self.safe_click(next_page_btn)
                            page.wait_for_timeout(3000)
                            current_page += 1
                        else:
                            self.log("Mentok! Tidak ada halaman selanjutnya.")
                            break
                    except: break
                else: break

            browser.close()
        return pd.DataFrame(rows)

    def run(self, keyword):
        df = self.scrape_blibli_logic(keyword)
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
            
            # Format Output Maps disamakan dengan Tokopedia
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

def scrape_blibli(keyword, callback=None, stop_check=None):
    scraper = BlibliGeoScraper(callback=callback, stop_check=stop_check)
    scraper.run(keyword)