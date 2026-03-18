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
MAPS_CTX = "Yogyakarta" # Digunakan untuk Query Google Maps
FILTER_CTX = "Kab. Bantul" # Digunakan untuk Filter Tokopedia
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
        
    # Karena kita filter Bantul di Tokopedia, kita cari lokasi Bantul
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

    def extract_tokopedia_shops(self, keyword, p):
        unique_shops = set()
        
        # Playwright Anti-Bot dengan Edge
        browser = p.chromium.launch(
            headless=False, 
            channel="msedge", 
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )

        context = browser.new_context(no_viewport=True) 
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get:()=>undefined})")
        page = context.new_page()

        try:
            self.log(f"Membuka browser... Mencari di Tokopedia: {keyword}")
            page.goto("https://www.tokopedia.com/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            # Pencarian
            search_box = page.locator('input[type="search"]').first
            if search_box.is_visible():
                search_box.click(force=True)
                search_box.fill(keyword)
                search_box.press("Enter")
                page.wait_for_timeout(5000)
            else:
                self.log("⚠️ Kotak pencarian tidak ditemukan.")
                return []

            # Menerapkan Filter Lokasi
            self.log(f"Menerapkan Filter Lokasi ({FILTER_CTX})...")
            filter_btn = page.locator('[data-testid="lnkSRPSeeAllLocFilter"]').first
            if filter_btn.is_visible():
                filter_btn.click(force=True)
                page.wait_for_timeout(2000)

                # Ketik "Kab. Bantul"
                loc_input = page.locator('input[aria-label="Cari lokasi"]').first
                if loc_input.is_visible():
                    loc_input.fill(FILTER_CTX)
                    page.wait_for_timeout(2000)

                # Pilih "Kab. Bantul"
                target_xpath = f'//*[contains(text(),"{FILTER_CTX}")]/ancestor::*[self::label or self::div or self::li][1]'
                target_lbl = page.locator(target_xpath).first
                if target_lbl.is_visible():
                    target_lbl.click(force=True)
                    page.wait_for_timeout(1000)

                # Terapkan
                apply_btn = page.locator('[data-testid="btnSRPApplySeeAllFilter"]').first
                if apply_btn.is_visible():
                    apply_btn.click(force=True)
                    page.wait_for_timeout(5000)
            else:
                self.log("Gagal membuka menu filter lokasi. Mencoba mengambil data yang ada...")

            # Scroll & Muat Lebih Banyak (Auto Stop saat Mentok)
            self.log("Memulai simulasi scroll ke bawah untuk memuat produk...")
            last_item_count = 0
            no_change_count = 0
            
            for i in range(50):
                if self.is_stopped(): break
                
                # Hitung produk dari jumlah gambar
                current_item_count = page.locator('img[alt="product-image"]').count()
                
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
                
                # Scroll perlahan ke bawah
                for _ in range(3):
                    page.mouse.wheel(0, 1500)
                    page.wait_for_timeout(800)
                    
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
                
                # Cari dan klik tombol "Muat Lebih Banyak"
                btn_xpath = '//button[contains(translate(text(), "MUAT LEBIH BANYAK", "muat lebih banyak"), "muat lebih banyak")]'
                load_more = page.locator(btn_xpath).first
                if load_more.is_visible():
                    self.log(f"Klik 'Muat Lebih Banyak' #{i+1}")
                    load_more.click(force=True)
                    page.wait_for_timeout(3500)

            # Scraping Kartu Tokopedia
            self.log("Scraping semua data yang sudah terbuka...")
            imgs = page.locator('img[alt="product-image"]').all()
            for img in imgs:
                if self.is_stopped(): break
                try:
                    # Ambil kartu produk yang lokasinya Bantul
                    card = img.locator("xpath=./ancestor::div[contains(translate(., 'BANTUL', 'bantul'), 'bantul')][1]").first
                    if card.is_visible():
                        texts = card.locator("span").all_inner_texts()
                        parsed = parse_card_texts(texts)
                        
                        shop_name = clean_text(parsed["shop_name"])
                        if shop_name and "bantul" in parsed["shop_location"].lower():
                            if shop_name not in unique_shops:
                                unique_shops.add(shop_name)
                                self.log(f"Ditemukan Toko: {shop_name}")
                except: pass

        finally:
            browser.close()
            
        return list(unique_shops)

    def enrich_google_maps(self, unique_shops, keyword, p):
        self.log(f"\nTotal toko unik: {len(unique_shops)}. Memulai pengayaan Maps...")
        
        # Buka Browser Maps secara Visual (Headless=False)
        browser = p.chromium.launch(headless=False, channel="msedge", args=["--start-maximized"])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        
        final_rows = []

        try:
            for shop in unique_shops:
                if self.is_stopped(): break
                
                # QUERY GOOGLE MAPS = {NAMA TOKO} YOGYAKARTA
                maps_query = f"{shop} {MAPS_CTX}"
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
                    # PERBAIKAN: Penargetan spesifik ke class "DUwDvf" agar tidak menangkap text "Hasil"
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

        # Format Excel Standar 17 Kolom
        output_df = pd.DataFrame(final_rows, columns=[
            "shop_name", "maps_query", "maps_place_name", "maps_address", 
            "name_similarity", "match_quality", "latitude", "longitude", 
            "phone", "website", "email", "maps_url", 
            "idsls", "nama_kecamatan", "nama_desa", "nama_sls", "status"
        ])
           
        output_file = os.path.join(f"{OUTPUT_PREFIX}_{sanitize_filename(keyword)}_enriched.xlsx")
        output_df.to_excel(output_file, index=False)
        self.log(f"✅ Selesai! File disimpan: {output_file}")

    def run(self, keyword):
        with sync_playwright() as p:
            unique_shops = self.extract_tokopedia_shops(keyword, p)
            if self.is_stopped() or not unique_shops:
                self.log("Tidak ada data untuk dilanjutkan ke Maps.")
                return
            
            self.enrich_google_maps(list(unique_shops), keyword, p)

def scrape_tokopedia(keyword, callback=None, stop_check=None):
    scraper = TokopediaGeoScraper(callback=callback, stop_check=stop_check)
    scraper.run(keyword)