import os
import time
import re
import json
import urllib.parse
from difflib import SequenceMatcher
import pandas as pd
from playwright.sync_api import sync_playwright

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

    def _handle_location_popup(self, page):
        self.log("Mengecek popup lokasi Blibli...")
        try:
            nanti_btn = page.locator("button.blu-button").filter(has_text=re.compile(r"Nanti saja", re.IGNORECASE)).first
            if nanti_btn.is_visible(timeout=3000):
                nanti_btn.click(force=True)
                page.wait_for_timeout(1000)
        except Exception:
            pass

    def _apply_filter(self, page):
        """Menerapkan filter menggunakan klik paksa Playwright"""
        self.log(f"Menerapkan filter Lokasi ({CTX})...")
        page.evaluate("window.scrollBy(0, 300)")
        page.wait_for_timeout(1500)

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
                    lihat_semua.click(force=True)
                    self.log("Klik tombol 'Lihat semua' lokasi...")
                    
                    # Tunggu modal muncul dengan selektor yang lebih fleksibel
                    modal = page.locator("div[class*='filter-desktop-modal'], div[class*='blu-modal']").first
                    modal.wait_for(state="visible", timeout=8000)
                    
                    search_input = modal.locator("input[type='text']").first
                    if search_input.is_visible():
                        search_input.click(force=True)
                        search_input.fill(CTX)
                        page.wait_for_timeout(2000) 
                        
                        checkbox_label = modal.locator("label.blu-checkbox").filter(has_text=re.compile(CTX, re.IGNORECASE)).first
                        if checkbox_label.is_visible():
                            checkbox_label.click(force=True)
                            self.log(f"Checkbox {CTX} dicentang!")
                            page.wait_for_timeout(1000)

                    simpan_btn = modal.locator("button.b-primary").filter(has_text=re.compile(r"Simpan|Terapkan", re.IGNORECASE)).first
                    if simpan_btn.is_visible():
                        simpan_btn.click(force=True)
                        self.log(f"Filter {CTX} BERHASIL disimpan.")
                        page.wait_for_timeout(4000)
                        return True
                else:
                    direct_check = target_group.locator("label").filter(has_text=re.compile(CTX, re.IGNORECASE)).first
                    if direct_check.is_visible():
                        direct_check.click(force=True)
                        self.log(f"Filter {CTX} (Langsung) BERHASIL diterapkan.")
                        page.wait_for_timeout(4000)
                        return True
        except Exception as e:
            self.log(f"Gagal menerapkan filter otomatis: {e}")
        return False

    def extract_blibli_shops(self, keyword, p):
        unique_shops = set()
        
        # MURNI PLAYWRIGHT: Anti-Blokir Blibli
        browser = p.chromium.launch(
            headless=False, 
            channel="msedge", 
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )

        context = browser.new_context(no_viewport=True) 
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get:()=>undefined})")
        page = context.new_page()
        detail_page = context.new_page() 

        try:
            self.log(f"Membuka browser... Mencari: {keyword}")
            page.goto("https://www.blibli.com/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            
            inp = page.locator("input[placeholder*='Cari'], input[type='search'], input[data-testid*='search']").first
            if inp.is_visible():
                inp.click(force=True)
                inp.fill(keyword)
                page.keyboard.press("Enter")
                page.wait_for_timeout(5000)
            else:
                self.log("⚠️ Kolom pencarian tidak ditemukan.")
                return []

            self._handle_location_popup(page)
            
            for _ in range(3):
                if self.is_stopped(): break
                if self._apply_filter(page): break
            
            current_page = 1
            max_pages = 10
            cards_data = []

            while current_page <= max_pages:
                if self.is_stopped(): break
                self.log(f"\n--- Memproses Halaman {current_page} ---")
                
                for _ in range(6):
                    page.mouse.wheel(0, 1200)
                    page.wait_for_timeout(1000)
                
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

                product_cards = page.locator("div.product-list__card, div[class*='product-card']").all()
                self.log(f"Menemukan {len(product_cards)} produk.")
                
                for card in product_cards:
                    if self.is_stopped(): break
                    try:
                        link_elem = card.locator("a").first
                        if link_elem.is_visible():
                            url = link_elem.get_attribute("href")
                            if url and url.startswith("/"): url = "https://www.blibli.com" + url
                            if url: cards_data.append({"url": url})
                    except: pass
                
                # Navigasi halaman yang sangat akurat
                if current_page < max_pages and not self.is_stopped():
                    try:
                        next_page_str = str(current_page + 1)
                        next_page_xpath = f"//div[contains(@class, 'blu-pagination__button-container')]//button[text()='{next_page_str}']"
                        next_page_btn = page.locator(next_page_xpath).first
                        
                        if next_page_btn.is_visible():
                            next_page_btn.scroll_into_view_if_needed()
                            next_page_btn.click(force=True)
                            self.log(f"Pindah ke halaman {next_page_str}...")
                            page.wait_for_timeout(4000)
                            current_page += 1
                        else:
                            self.log("Mentok! Halaman selanjutnya tidak ditemukan.")
                            break
                    except Exception: break
                else: break

            self.log(f"Mengekstrak {len(cards_data)} URL untuk menemukan Nama Toko...")
            for idx, item in enumerate(cards_data):
                if self.is_stopped(): break
                try:
                    detail_page.goto(item["url"], wait_until="domcontentloaded", timeout=40000)
                    detail_page.wait_for_timeout(2000)

                    shop_selectors = [
                        "span.seller-name__name", "span[class*='seller-name']", 
                        "div[class*='merchant-name']", "a[class*='merchant-name']",
                        "h2[class*='merchant-name']", "[data-testid='merchant-name']"
                    ]
                    shop_name = ""
                    for sel in shop_selectors:
                        shop_elem = detail_page.locator(sel).first
                        if shop_elem.is_visible():
                            shop_name = clean_text(shop_elem.text_content())
                            break
                    
                    if not shop_name or shop_name.lower() in ["yogyakarta", "kota yogyakarta", "sleman", "bantul", "kab. bantul"]:
                        continue
                        
                    if shop_name not in unique_shops:
                        unique_shops.add(shop_name)
                        self.log(f"  [{idx+1}/{len(cards_data)}] Ditemukan Toko: {shop_name}")
                except: pass

        finally:
            browser.close()
            
        return list(unique_shops)

    def enrich_google_maps(self, unique_shops, keyword, p):
        self.log(f"\nTotal toko unik: {len(unique_shops)}. Memulai pengayaan Maps...")
        
        # MURNI PLAYWRIGHT: Maps juga Headless=False agar terlihat!
        browser = p.chromium.launch(headless=False, channel="msedge", args=["--start-maximized"])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        
        final_rows = []

        try:
            for shop in unique_shops:
                if self.is_stopped(): break
                
                # Format Query
                maps_query = f"{shop} {CTX}"
                self.log(f"Mencari di Maps: {maps_query}")
                
                url = "https://www.google.com/maps/search/" + urllib.parse.quote(maps_query)
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                
                try:
                    place_links = page.locator('a[href*="/place/"]').all()
                    if place_links:
                        place_links[0].click(force=True)
                        page.wait_for_timeout(3000)
                except: pass

                maps_url = page.url
                
                maps_place_name = ""
                try:
                    # PERBAIKAN: Gunakan class DUwDvf spesifik agar tidak menangkap teks "Hasil"
                    h1 = page.locator("h1.DUwDvf").first
                    if h1.is_visible(timeout=3000):
                        maps_place_name = clean_text(h1.text_content())
                    else: 
                        maps_place_name = shop
                except: 
                    maps_place_name = shop

                maps_address = ""
                try:
                    btn_addr = page.locator('button[data-item-id="address"]').first
                    if btn_addr.is_visible():
                        maps_address = btn_addr.get_attribute("aria-label").replace("Alamat: ", "").strip()
                        if not maps_address:
                            maps_address = clean_text(btn_addr.text_content())
                except: pass

                phone = ""
                try:
                    btn_phone = page.locator('button[data-item-id^="phone:tel:"]').first
                    if btn_phone.is_visible():
                        phone = btn_phone.get_attribute("aria-label").replace("Nomor telepon: ", "").strip()
                        if not phone:
                            phone = clean_text(btn_phone.text_content())
                except: pass

                m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+),", maps_url)
                lat, lng = (float(m.group(1)), float(m.group(2))) if m else (None, None)
                
                geo_info = self.find_geojson_match(lat, lng)
                
                if lat is None:
                    status = "NOT_FOUND"
                else:
                    status = "DALAM_RING" if geo_info else "DILUAR_RING"
                
                similarity = SequenceMatcher(None, shop.lower(), maps_place_name.lower()).ratio()
                if similarity >= 0.8: match_quality = "TINGGI"
                elif similarity >= 0.5: match_quality = "SEDANG"
                else: match_quality = "RENDAH"

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
                    "website": "",
                    "email": "",
                    "maps_url": maps_url,
                    "idsls": geo_info["idsls"] if geo_info else "",
                    "nama_kecamatan": geo_info["nama_kecamatan"] if geo_info else "",
                    "nama_desa": geo_info["nama_desa"] if geo_info else "",
                    "nama_sls": geo_info["nama_sls"] if geo_info else "",
                    "status": status
                })
                self.log(f"Maps: {shop} -> {status} | Sim: {round(similarity, 2)} | Telp: {phone}")

        finally:
            browser.close()

        # Format BPS 17 Kolom
        output_df = pd.DataFrame(final_rows, columns=[
            "shop_name", "maps_query", "maps_place_name", "maps_address", 
            "name_similarity", "match_quality", "latitude", "longitude", 
            "phone", "website", "email", "maps_url", 
            "idsls", "nama_kecamatan", "nama_desa", "nama_sls", "status"
        ])
        
        output_file = os.path.join(f"{sanitize_filename(keyword)}_{OUTPUT_PREFIX}_enriched.xlsx")
        output_df.to_excel(output_file, index=False)
        self.log(f"✅ Selesai! File disimpan: {output_file}")

    def run(self, keyword):
        # Seluruh siklus dibungkus dalam Playwright!
        with sync_playwright() as p:
            unique_shops = self.extract_blibli_shops(keyword, p)
            if self.is_stopped() or not unique_shops:
                self.log("Tidak ada data untuk dilanjutkan ke Maps.")
                return
            
            self.enrich_google_maps(list(unique_shops), keyword, p)

def scrape_blibli(keyword, callback=None, stop_check=None):
    scraper = BlibliGeoScraper(callback=callback, stop_check=stop_check)
    scraper.run(keyword)