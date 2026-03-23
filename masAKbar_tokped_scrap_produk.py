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


# ================= CONFIG =================

GEOJSON_FILE = "idsls fix.geojson"
CTX = "Bantul"
OUTPUT_PREFIX = "tokopedia"


# ================= UTILITY =================

def sanitize_filename(text):
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "output"


def safe_click(locator):
    try:
        locator.click(timeout=8000)
        return True
    except:
        try:
            locator.scroll_into_view_if_needed(timeout=3000)
            time.sleep(1)
            locator.click(timeout=8000, force=True)
            return True
        except:
            return False


def normalize_name(text):
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def name_similarity(a, b):
    a = normalize_name(a)
    b = normalize_name(b)
    if not a or not b:
        return 0.0
    return round(SequenceMatcher(None, a, b).ratio(), 4)


def classify_match(similarity):
    if similarity >= 0.85:
        return "TINGGI"
    if similarity >= 0.65:
        return "SEDANG"
    if similarity >= 0.45:
        return "RENDAH"
    return "SANGAT_RENDAH"


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def parse_card_texts(texts):
    texts = [clean_text(t) for t in texts if clean_text(t)]

    product_name = ""
    price = ""
    sold = ""
    shop_name = ""
    shop_location = ""

    # harga
    for t in texts:
        if not price and t.lower().startswith("rp"):
            price = t
            break

    # sold
    for t in texts:
        if not sold and "terjual" in t.lower():
            sold = t
            break

    # cari pasangan shop_name + Kab. Bantul
    for i in range(len(texts) - 1):
        a = texts[i]
        b = texts[i + 1]
        if "bantul" in b.lower():
            shop_name = a
            shop_location = b
            break

    # product_name = text pertama yang bukan price/sold/shop/location
    for t in texts:
        if t == price or t == sold or t == shop_name or t == shop_location:
            continue
        if len(t) >= 4:
            product_name = t
            break

    return {
        "product_name": product_name,
        "price": price,
        "sold": sold,
        "shop_name": shop_name,
        "shop_location": shop_location
    }


# ================= LOAD GEOJSON =================

with open(GEOJSON_FILE, "r", encoding="utf-8") as f:
    gj = json.load(f)


def point_in_poly(lat, lng, ring):
    x, y = lng, lat
    inside = False
    n = len(ring)

    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]

        if (y1 > y) != (y2 > y):
            xinters = (x2 - x1) * (y - y1) / ((y2 - y1) + 1e-15) + x1
            if x < xinters:
                inside = not inside

    return inside


def find_geojson_match(lat, lng):
    if lat is None or lng is None:
        return None

    for feature in gj.get("features", []):
        geom = feature.get("geometry", {})
        props = feature.get("properties", {})

        geom_type = geom.get("type")
        coords = geom.get("coordinates", [])

        try:
            if geom_type == "Polygon":
                rings = [coords[0]] if coords else []
            elif geom_type == "MultiPolygon":
                rings = [poly[0] for poly in coords if poly]
            else:
                rings = []
        except:
            rings = []

        for ring in rings:
            try:
                lngs = [p[0] for p in ring]
                lats = [p[1] for p in ring]

                if not (min(lats) <= lat <= max(lats) and min(lngs) <= lng <= max(lngs)):
                    continue

                if point_in_poly(lat, lng, ring):
                    return {
                        "idsls": props.get("idsls", ""),
                        "nama_kabupaten": props.get("nmkab", ""),
                        "nama_kecamatan": props.get("nmkec", ""),
                        "nama_desa": props.get("nmdesa", ""),
                        "nama_sls": props.get("nmsls", "")
                    }
            except:
                pass

    return None


# ================= TOKOPEDIA SCRAPER =================

def click_load_more_until_end(page, max_rounds=200):
    print("Klik 'Muat Lebih Banyak' sampai habis...")
    for i in range(max_rounds):
        try:
            btn = page.locator('button:has-text("Muat Lebih Banyak")').first
            if btn.count() == 0:
                print("Tombol 'Muat Lebih Banyak' sudah habis.")
                break

            if not btn.is_visible():
                print("Tombol 'Muat Lebih Banyak' tidak visible.")
                break

            if not safe_click(btn):
                print("Gagal klik 'Muat Lebih Banyak'.")
                break

            print(f"Klik Muat Lebih Banyak #{i+1}")
            page.wait_for_timeout(2500)
        except:
            print("Tidak ada lagi tombol 'Muat Lebih Banyak'.")
            break


def scrape_tokopedia(keyword):
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        print("Buka Tokopedia...")
        page.goto("https://www.tokopedia.com", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        try:
            page.keyboard.press("Escape")
        except:
            pass

        search_box = page.locator('input[type="search"]').first
        search_box.wait_for(state="visible", timeout=15000)
        search_box.click()
        search_box.fill(keyword)
        search_box.press("Enter")
        page.wait_for_timeout(5000)

        print("Filter Kab. Bantul...")
        see_all_loc = page.locator('[data-testid="lnkSRPSeeAllLocFilter"]').first
        see_all_loc.wait_for(state="visible", timeout=15000)

        if not safe_click(see_all_loc):
            page.screenshot(path="debug_gagal_klik_filter_lokasi.png", full_page=True)
            print("Gagal klik filter lokasi.")
            browser.close()
            return pd.DataFrame(columns=[
                "shop_name", "shop_location", "product_name", "price", "sold", "product_url", "image_url"
            ])

        page.wait_for_timeout(2000)

        print("Isi Cari lokasi: Kab. Bantul")
        lokasi_input = page.locator('input[aria-label="Cari lokasi"]').first
        lokasi_input.wait_for(state="visible", timeout=15000)
        lokasi_input.click()
        lokasi_input.fill("Kab. Bantul")
        page.wait_for_timeout(2500)

        print("Klik checkbox Kab. Bantul...")
        target_checkbox = page.locator(
            'xpath=//*[contains(normalize-space(text()),"Kab. Bantul")]/ancestor::*[self::label or self::div or self::li][1]'
        ).first
        target_checkbox.wait_for(state="visible", timeout=10000)

        if not safe_click(target_checkbox):
            page.screenshot(path="debug_gagal_pilih_checkbox_bantul.png", full_page=True)
            print("Gagal klik checkbox Kab. Bantul.")
            browser.close()
            return pd.DataFrame(columns=[
                "shop_name", "shop_location", "product_name", "price", "sold", "product_url", "image_url"
            ])

        page.wait_for_timeout(1000)

        print("Klik Terapkan...")
        apply_btn = page.locator('[data-testid="btnSRPApplySeeAllFilter"]').first
        apply_btn.wait_for(state="visible", timeout=15000)

        if not safe_click(apply_btn):
            page.screenshot(path="debug_gagal_klik_terapkan.png", full_page=True)
            print("Gagal klik Terapkan.")
            browser.close()
            return pd.DataFrame(columns=[
                "shop_name", "shop_location", "product_name", "price", "sold", "product_url", "image_url"
            ])

        page.wait_for_timeout(5000)

        click_load_more_until_end(page)
        page.wait_for_timeout(2000)

        print("Parse semua kartu produk...")

        product_imgs = page.locator('img[alt="product-image"]')
        img_count = product_imgs.count()
        print("Total image produk:", img_count)

        seen_cards = set()

        for i in range(img_count):
            try:
                img = product_imgs.nth(i)

                # Naik ke root card berdasarkan struktur umum yang kamu kirim
                card = img.locator("xpath=ancestor::div[contains(., 'Kab. Bantul')][1]")
                if card.count() == 0:
                    continue

                texts = card.locator("span").all_inner_texts()
                parsed = parse_card_texts(texts)

                shop_name = clean_text(parsed["shop_name"])
                shop_location = clean_text(parsed["shop_location"])

                if not shop_name:
                    continue

                if "bantul" not in shop_location.lower():
                    continue

                image_url = ""
                try:
                    image_url = img.get_attribute("src") or ""
                except:
                    pass

                product_url = ""
                try:
                    links = card.locator("a")
                    for j in range(links.count()):
                        href = links.nth(j).get_attribute("href", timeout=1000)
                        if href:
                            product_url = href
                            break
                except:
                    pass

                row_key = (
                    normalize_name(shop_name),
                    normalize_name(parsed["product_name"]),
                    product_url
                )
                if row_key in seen_cards:
                    continue
                seen_cards.add(row_key)

                rows.append({
                    "shop_name": shop_name,
                    "shop_location": shop_location,
                    "product_name": parsed["product_name"],
                    "price": parsed["price"],
                    "sold": parsed["sold"],
                    "product_url": product_url,
                    "image_url": image_url
                })

                print("TOKOPEDIA:", shop_name, "|", parsed["product_name"], "|", shop_location)

            except:
                pass

        browser.close()

    df = pd.DataFrame(rows)

    if len(df) == 0:
        return pd.DataFrame(columns=[
            "shop_name", "shop_location", "product_name", "price", "sold", "product_url", "image_url"
        ])

    df = df.drop_duplicates(subset=["shop_name"]).reset_index(drop=True)
    return df


# ================= GOOGLE MAPS =================

def setup_maps_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    return driver


def extract_latlng(url):
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+),", url)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def extract_phone(driver):
    try:
        el = driver.find_element(By.CSS_SELECTOR, 'button[data-item-id^="phone"]')
        return el.text
    except:
        return ""


def extract_website(driver):
    try:
        el = driver.find_element(By.CSS_SELECTOR, 'a[data-item-id="authority"]')
        return el.get_attribute("href")
    except:
        return ""


def extract_maps_place_name(driver):
    selectors = [
        "h1",
        'h1[class]',
        'div[role="main"] h1',
    ]
    for sel in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text:
                return text
        except:
            pass
    return ""


def extract_email(url):
    if not url:
        return ""

    try:
        r = requests.get(url, timeout=8)
        emails = re.findall(
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}",
            r.text
        )
        if emails:
            return emails[0]
    except:
        pass

    return ""


def enrich_google_maps(df):
    driver = setup_maps_driver()

    for i, row in df.iterrows():
        shop = row["shop_name"]
        query = f"{shop}, {CTX}"
        url = "https://www.google.com/maps/search/" + urllib.parse.quote(query)

        driver.get(url)
        time.sleep(4)

        try:
            place_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/place/"]')
            if place_links:
                place_links[0].click()
                time.sleep(3)
        except:
            pass

        lat, lng = extract_latlng(driver.current_url)

        maps_place_name = extract_maps_place_name(driver)
        similarity = name_similarity(shop, maps_place_name)
        match_quality = classify_match(similarity)

        phone = extract_phone(driver)
        website = extract_website(driver)
        email = extract_email(website)

        geo_info = find_geojson_match(lat, lng)

        inside_ring = geo_info is not None
        status = "DALAM_RING" if inside_ring else "DILUAR_RING"

        df.at[i, "maps_place_name"] = maps_place_name
        df.at[i, "name_similarity"] = similarity
        df.at[i, "match_quality"] = match_quality
        df.at[i, "inside_ring"] = inside_ring
        df.at[i, "idsls"] = geo_info["idsls"] if geo_info else ""
        df.at[i, "nama_kabupaten"] = geo_info["nama_kabupaten"] if geo_info else ""
        df.at[i, "nama_kecamatan"] = geo_info["nama_kecamatan"] if geo_info else ""
        df.at[i, "nama_desa"] = geo_info["nama_desa"] if geo_info else ""
        df.at[i, "nama_sls"] = geo_info["nama_sls"] if geo_info else ""
        df.at[i, "latitude"] = lat
        df.at[i, "longitude"] = lng
        df.at[i, "phone"] = phone
        df.at[i, "website"] = website
        df.at[i, "email"] = email
        df.at[i, "maps_url"] = driver.current_url
        df.at[i, "status"] = status

        print(
            "MAPS:",
            shop,
            "|",
            maps_place_name,
            "| sim:",
            similarity,
            "|",
            lat,
            lng,
            "|",
            status,
            "|",
            geo_info["idsls"] if geo_info else "-"
        )
        time.sleep(1.5)

    driver.quit()
    return df


# ================= MAIN =================

def main():
    keyword = input("Keyword Tokopedia: ").strip()

    if not keyword:
        print("Keyword tidak boleh kosong")
        return

    df = scrape_tokopedia(keyword)

    print("\nTotal toko unik:", len(df))

    if len(df) == 0:
        print("Tidak ada data Tokopedia yang berhasil diambil.")
        return

    df = enrich_google_maps(df)

    keyword_safe = sanitize_filename(keyword)
    output_file = f"{OUTPUT_PREFIX}_{keyword_safe}_bantul_enriched.xlsx"

    df.to_excel(output_file, index=False)

    print("\nSELESAI")
    print("Output:", output_file)


if __name__ == "__main__":
    main()