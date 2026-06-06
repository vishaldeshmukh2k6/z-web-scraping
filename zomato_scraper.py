from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import json
import re
import os
from dotenv import load_dotenv

load_dotenv()


def get_driver():
    options = Options()
    options.binary_location = os.getenv("CHROME_BINARY")
    # options.add_argument("--headless=new")  # Commented out so Chrome is visible
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"user-agent={os.getenv('USER_AGENT')}")
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


def get_links_after_one_scroll(driver):
    # Scroll through the page slowly to trigger lazy loading of images
    try:
        total_height = driver.execute_script("return document.body.scrollHeight")
        for pos in range(0, total_height, 500):
            driver.execute_script(f"window.scrollTo(0, {pos});")
            time.sleep(0.3)
        # Scroll back to bottom
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
    except:
        pass

    cards = driver.find_elements(By.CSS_SELECTOR, "div[class*='jumbo-tracker']")
    results = {}  # { url: card_image_url }
    for card in cards:
        try:
            a_tags = card.find_elements(By.TAG_NAME, "a")
            if len(a_tags) >= 2:
                href = a_tags[1].get_attribute("href") or ""
                if "/info" in href:
                    url = href.replace("/info", "")
                    # Grab the restaurant thumbnail — the large hero image on the card
                    card_img = "N/A"
                    try:
                        img_els = card.find_elements(By.TAG_NAME, "img")
                        for img_el in img_els:
                            src = (img_el.get_attribute("src")
                                   or img_el.get_attribute("data-src")
                                   or img_el.get_attribute("srcset")
                                   or "")
                            if not src:
                                continue
                            # Skip promo badges, logos, icons, assets
                            if "o2_assets" in src or "logo" in src or "icon" in src or "web_assets" in src:
                                continue
                            # The restaurant thumbnail is from /data/pictures
                            if "zmtcdn.com/data/pictures" in src or "zmtcdn.com/data/reviews_photos" in src:
                                card_img = src.split(",")[0].strip()  # handle srcset format
                                break
                        # Fallback: any zmtcdn image that's not an asset
                        if card_img == "N/A":
                            for img_el in img_els:
                                src = (img_el.get_attribute("src")
                                       or img_el.get_attribute("data-src")
                                       or "")
                                if not src:
                                    continue
                                if "o2_assets" in src or "logo" in src or "icon" in src or "web_assets" in src:
                                    continue
                                if "zmtcdn.com" in src:
                                    card_img = src
                                    break
                    except:
                        pass
                    results[url] = card_img
        except:
            continue
    return results  # returns dict {url: card_image}


def scrape_menu_images(driver, url):
    """On the /info page, scroll to menu section, click each menu card
    to open popup, navigate pages with arrow, collect images."""
    from selenium.webdriver.common.keys import Keys

    menu_images = {}  # { "Food Menu": [img1, img2, ...], "Bar Menu": [...] }

    try:
        # Scroll down to make menu section visible
        driver.execute_script("window.scrollTo(0, 800);")
        time.sleep(2)

        # First pass: count how many menu cards exist
        def find_menu_cards():
            """Re-find all clickable menu cards on the page."""
            page_indicators = driver.find_elements(
                By.XPATH,
                "//p[contains(text(),'page')]"
            )
            cards = []
            for indicator in page_indicators:
                try:
                    text = indicator.text.strip().lower()
                    if "page" not in text:
                        continue
                    # The direct parent div (with cursor:pointer) is the clickable card
                    parent = indicator.find_element(By.XPATH, "./..")
                    cursor = parent.value_of_css_property("cursor")
                    if cursor == "pointer":
                        clickable = parent
                    else:
                        clickable = parent
                        for _ in range(3):
                            clickable = clickable.find_element(By.XPATH, "./..")
                            if clickable.value_of_css_property("cursor") == "pointer":
                                break

                    # Get menu name from sibling h4 heading
                    container = clickable.find_element(By.XPATH, "./..")
                    h4_els = container.find_elements(By.TAG_NAME, "h4")
                    if h4_els:
                        menu_name = h4_els[0].text.strip()
                    else:
                        card_text = clickable.text.strip()
                        lines = [l.strip() for l in card_text.split("\n") if l.strip()]
                        menu_name = "Menu"
                        for line in lines:
                            if "menu" in line.lower() and "page" not in line.lower():
                                menu_name = line
                                break

                    # Skip promo/offer cards (not actual menus)
                    promo_keywords = ["off", "flat", "discount", "offer", "deal", "free", "cashback", "save"]
                    if any(kw in menu_name.lower() for kw in promo_keywords):
                        continue

                    cards.append((menu_name, clickable))
                except:
                    continue
            return cards

        # Get initial count of menu cards
        initial_cards = find_menu_cards()
        total_menus = len(initial_cards)
        menu_names = [name for name, _ in initial_cards]

        if total_menus == 0:
            # Fallback: find menu thumbnail images with /data/menus/ in src
            menu_thumbs = driver.find_elements(
                By.CSS_SELECTOR,
                "img[src*='/data/menus/']"
            )
            total_menus = len(menu_thumbs)
            menu_names = [f"Menu {i+1}" for i in range(total_menus)]

        print(f"      📋 Found {total_menus} menu(s) to scrape")

        for idx in range(total_menus):
            try:
                # Re-find cards fresh each iteration to avoid stale references
                current_cards = find_menu_cards()
                if idx >= len(current_cards):
                    print(f"      ⚠️  Card {idx} no longer found, skipping")
                    continue

                menu_name, card_element = current_cards[idx]
                print(f"      📖 Opening: {menu_name}")

                # Click the menu card to open popup
                driver.execute_script("arguments[0].click();", card_element)
                time.sleep(3)

                page_images = []
                seen_srcs = set()
                max_pages = 50

                for page_num in range(max_pages):
                    # Grab menu images — only from /data/menus/ path (actual menu pages)
                    popup_imgs = driver.find_elements(
                        By.CSS_SELECTOR, "img[src*='/data/menus/']"
                    )

                    for img in popup_imgs:
                        src = img.get_attribute("src") or ""
                        if not src or src in seen_srcs:
                            continue
                        # Only collect actual menu page images (large ones)
                        natural_w = driver.execute_script(
                            "return arguments[0].naturalWidth || 0;", img
                        )
                        if natural_w > 300:
                            clean_src = src.split("?")[0] if "?" in src else src
                            seen_srcs.add(src)
                            page_images.append(clean_src)

                    # Try to navigate to next page using keyboard arrow
                    try:
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
                        time.sleep(2)

                        # Check if a new menu image appeared
                        new_imgs = driver.find_elements(
                            By.CSS_SELECTOR, "img[src*='/data/menus/']"
                        )
                        has_new = False
                        for img in new_imgs:
                            src = img.get_attribute("src") or ""
                            if src and src not in seen_srcs:
                                natural_w = driver.execute_script(
                                    "return arguments[0].naturalWidth || 0;", img
                                )
                                if natural_w > 300:
                                    has_new = True
                                    break

                        if not has_new:
                            # Try clicking right-side arrow buttons
                            arrows = driver.find_elements(
                                By.CSS_SELECTOR,
                                "[class*='next'], [class*='right'], [aria-label*='next' i], [aria-label*='Next']"
                            )
                            if not arrows:
                                candidates = driver.find_elements(
                                    By.CSS_SELECTOR,
                                    "div[role='button'], button, span[role='button'], div[tabindex]"
                                )
                                for el in candidates:
                                    try:
                                        loc = el.location
                                        size = el.size
                                        inner = el.get_attribute("innerHTML") or ""
                                        if loc['x'] > 800 and size['height'] > 20 and "svg" in inner.lower():
                                            arrows.append(el)
                                    except:
                                        pass

                            if arrows:
                                driver.execute_script("arguments[0].click();", arrows[0])
                                time.sleep(2)
                                new_imgs = driver.find_elements(
                                    By.CSS_SELECTOR, "img[src*='/data/menus/']"
                                )
                                for img in new_imgs:
                                    src = img.get_attribute("src") or ""
                                    if src and src not in seen_srcs:
                                        natural_w = driver.execute_script(
                                            "return arguments[0].naturalWidth || 0;", img
                                        )
                                        if natural_w > 300:
                                            has_new = True
                                            break

                            if not has_new:
                                break
                    except:
                        break

                if page_images:
                    menu_images[menu_name] = page_images
                    print(f"        ✓ {len(page_images)} page(s) collected")
                else:
                    print(f"        ✗ No pages collected")

                # Close the popup — press Escape
                try:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(2)
                except:
                    pass

            except Exception as e:
                print(f"      ⚠️  Error with menu {idx}: {e}")
                try:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(1)
                except:
                    pass
                continue

    except Exception as e:
        print(f"      ⚠️  Error scraping menus: {e}")

    return menu_images


def scrape_restaurant_detail(driver, url, card_image="N/A"):
    driver.get(url)
    time.sleep(3)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)

    data = {"url": url, "thumbnail": card_image}  # thumbnail from listing page
    page_source = driver.page_source

    # Name
    try:
        data["name"] = driver.find_element(By.CSS_SELECTOR, "h1").text.strip()
    except:
        data["name"] = "N/A"

    # Cuisines
    try:
        cuisine_header = driver.find_elements(By.XPATH, "//*[text()='Cuisines']")
        if cuisine_header:
            parent = cuisine_header[0].find_element(By.XPATH, "./..")
            text = parent.text.replace("Cuisines", "").strip()
            data["cuisines"] = [c.strip() for c in text.split("\n") if c.strip()]
        else:
            data["cuisines"] = []
    except:
        data["cuisines"] = []

    # Address
    try:
        p_els = driver.find_elements(By.CSS_SELECTOR, "p")
        for el in p_els:
            text = el.text.strip()
            if ("Mumbai" in text or "Navi Mumbai" in text or "Thane" in text) and len(text) > 15:
                data["address"] = text
                break
        if "address" not in data:
            data["address"] = "N/A"
    except:
        data["address"] = "N/A"

    # Dining Rating + Count
    try:
        sections = driver.find_elements(By.XPATH, "//*[contains(text(),'Dining Rating')]/..")
        if sections:
            text = sections[0].text
            match = re.search(r'([\d.]+)\s*[\n\s]*([\d,]+)\s*Dining Rating', text)
            if match:
                data["dining_rating"] = match.group(1)
                data["dining_rating_count"] = match.group(2)
            else:
                data["dining_rating"] = "N/A"
                data["dining_rating_count"] = "0"
        else:
            data["dining_rating"] = "N/A"
            data["dining_rating_count"] = "0"
    except:
        data["dining_rating"] = "N/A"
        data["dining_rating_count"] = "0"

    # Delivery Rating + Count
    try:
        sections = driver.find_elements(By.XPATH, "//*[contains(text(),'Delivery Rating')]/..")
        if sections:
            text = sections[0].text
            match = re.search(r'([\d.]+)\s*[\n\s]*([\d,]+)\s*Delivery Rating', text)
            if match:
                data["delivery_rating"] = match.group(1)
                data["delivery_rating_count"] = match.group(2)
            else:
                data["delivery_rating"] = "N/A"
                data["delivery_rating_count"] = "0"
        else:
            data["delivery_rating"] = "N/A"
            data["delivery_rating_count"] = "0"
    except:
        data["delivery_rating"] = "N/A"
        data["delivery_rating_count"] = "0"

    # Cost for two
    try:
        cost_match = re.search(r'₹[\d,]+\s*for two', page_source)
        data["cost_for_two"] = cost_match.group(0) if cost_match else "N/A"
    except:
        data["cost_for_two"] = "N/A"

    # Phone numbers
    try:
        phone_els = driver.find_elements(By.CSS_SELECTOR, "a[href^='tel:']")
        phones = list(set(p.get_attribute("href").replace("tel:", "") for p in phone_els))
        data["phone"] = phones if phones else []
    except:
        data["phone"] = []

    # Status & Timing
    try:
        time_els = driver.find_elements(By.XPATH, "//*[contains(text(),'Opens') or contains(text(),'Open now') or contains(text(),'Closed')]")
        for el in time_els:
            text = el.text.strip()
            if ("Open" in text or "Closed" in text) and len(text) < 50:
                data["status"] = text
                break
        if "status" not in data:
            data["status"] = "N/A"
    except:
        data["status"] = "N/A"

    # Top Dishes
    try:
        header = driver.find_elements(By.XPATH, "//*[text()='Top dishes']")
        if header:
            parent = header[0].find_element(By.XPATH, "./..")
            text = parent.text.replace("Top dishes", "").strip()
            data["top_dishes"] = [d.strip() for d in text.split("\n") if d.strip()]
        else:
            data["top_dishes"] = []
    except:
        data["top_dishes"] = []

    # Direction link (Google Maps)
    try:
        map_el = driver.find_element(By.CSS_SELECTOR, "a[href*='google.com/maps']")
        data["direction_link"] = map_el.get_attribute("href")
    except:
        data["direction_link"] = "N/A"

    # Images
    try:
        img_els = driver.find_elements(By.TAG_NAME, "img")
        images = set()
        for img in img_els:
            src = img.get_attribute("src") or ""
            if "zmtcdn.com/data/pictures" in src or "zmtcdn.com/data/reviews_photos" in src:
                images.add(src)
        data["images"] = list(images)
    except:
        data["images"] = []

    # Menu images - click menu cards on info page, navigate popup pages
    # Done last since popup interactions may alter page state
    data["menu_images"] = scrape_menu_images(driver, url)

    data["reviews_link"] = url + "/reviews"
    data["photos_link"] = url + "/photos"

    return data



def get_restaurant_id(url):
    """Extract restaurant ID from Zomato URL (last path segment)."""
    try:
        # e.g. https://www.zomato.com/mumbai/rasoi-dadar-east -> rasoi-dadar-east
        path = url.rstrip("/").split("/")[-1]
        return path
    except:
        return None


def get_city_from_url(url):
    """Extract city name from Zomato URL."""
    try:
        # e.g. https://www.zomato.com/mumbai/rasoi-dadar-east -> mumbai
        parts = url.rstrip("/").split("/")
        # Find the part after zomato.com
        for i, part in enumerate(parts):
            if "zomato.com" in part and i + 1 < len(parts):
                return parts[i + 1].lower()
    except:
        pass
    return "mumbai"


import threading

_save_lock = threading.Lock()


def save_restaurant(data, city="mumbai"):
    """Save individual restaurant JSON and update the combined restaurants.json. Thread-safe."""
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", city)
    restaurants_dir = os.path.join(base_dir, "restaurants")
    os.makedirs(restaurants_dir, exist_ok=True)

    restaurant_id = get_restaurant_id(data.get("url", ""))
    if not restaurant_id:
        return False

    # Save individual restaurant file
    individual_file = os.path.join(restaurants_dir, f"{restaurant_id}.json")
    with open(individual_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Update combined restaurants.json (thread-safe)
    with _save_lock:
        try:
            combined_file = os.path.join(base_dir, "restaurants.json")
            if os.path.exists(combined_file):
                with open(combined_file, "r", encoding="utf-8") as f:
                    all_restaurants = json.load(f)
            else:
                all_restaurants = []

            # Replace if already exists, else append
            updated = False
            for i, r in enumerate(all_restaurants):
                if get_restaurant_id(r.get("url", "")) == restaurant_id:
                    all_restaurants[i] = data
                    updated = True
                    break
            if not updated:
                all_restaurants.append(data)

            with open(combined_file, "w", encoding="utf-8") as f:
                json.dump(all_restaurants, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"      ⚠️  Error updating restaurants.json: {e}")

    return True


def is_already_scraped(url, city="mumbai"):
    """Check if a restaurant has already been scraped."""
    restaurant_id = get_restaurant_id(url)
    if not restaurant_id:
        return False
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", city)
    individual_file = os.path.join(base_dir, "restaurants", f"{restaurant_id}.json")
    return os.path.exists(individual_file)

def scrape_restaurant_worker(args):
    """Worker function for thread pool — each thread gets its own browser."""
    url, card_image, city = args
    driver = None
    try:
        driver = get_driver()
        data = scrape_restaurant_detail(driver, url, card_image)
        save_restaurant(data, city)
        print(f"    ✓ {data.get('name', 'N/A')} — {url.split('/')[-1]}")
        return data
    except Exception as e:
        print(f"    ✗ Error: {url.split('/')[-1]} — {e}")
        return None
    finally:
        try:
            if driver:
                driver.quit()
        except:
            pass


# ---- MAIN ----
if __name__ == "__main__":
    import random
    from concurrent.futures import ThreadPoolExecutor, as_completed

    MAX_RESTAURANTS = int(os.getenv("MAX_RESTAURANTS", 50))
    CITY = os.getenv("CITY", "mumbai")
    DELAY_MIN = int(os.getenv("DELAY_MIN", 4))
    DELAY_MAX = int(os.getenv("DELAY_MAX", 8))
    SCROLL_DELAY_MIN = int(os.getenv("SCROLL_DELAY_MIN", 5))
    SCROLL_DELAY_MAX = int(os.getenv("SCROLL_DELAY_MAX", 8))
    WORKERS = int(os.getenv("WORKERS", 5))

    # Use one main driver just for the listing page scrolling
    driver = get_driver()

    try:
        print(f"🌐 Loading Zomato {CITY.title()} restaurants page...")
        print(f"   Config: max={MAX_RESTAURANTS}, workers={WORKERS}")
        driver.get(os.getenv("BASE_URL"))
        time.sleep(random.uniform(SCROLL_DELAY_MIN, SCROLL_DELAY_MAX))

        already_seen_links = set()
        total_saved = 0
        total_skipped = 0
        scroll_num = 0
        consecutive_empty = 0

        while total_saved < MAX_RESTAURANTS:
            scroll_num += 1
            print(f"\n{'='*60}")
            print(f"📜 Scroll {scroll_num} (saved: {total_saved}/{MAX_RESTAURANTS}, skipped: {total_skipped})...")

            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(SCROLL_DELAY_MIN, SCROLL_DELAY_MAX))

                current_links = get_links_after_one_scroll(driver)
                new_links_dict = {url: img for url, img in current_links.items() if url not in already_seen_links}
                already_seen_links.update(new_links_dict.keys())
            except Exception as e:
                print(f"  ⚠️  Error during scroll/link extraction: {e}")
                time.sleep(5)
                continue

            print(f"  🔗 {len(new_links_dict)} new restaurant links found")

            if not new_links_dict:
                consecutive_empty += 1
                print(f"  ⚠️  No new links found ({consecutive_empty}/5)...")
                if consecutive_empty >= 5:
                    print("  🏁 No more restaurants to scrape. Stopping.")
                    break
                time.sleep(random.uniform(3, 5))
                continue

            consecutive_empty = 0

            # Filter out already scraped
            to_scrape = []
            for link, card_image in new_links_dict.items():
                if total_saved + len(to_scrape) >= MAX_RESTAURANTS:
                    break
                try:
                    if is_already_scraped(link, CITY):
                        total_skipped += 1
                        print(f"  ⏭️  Already scraped: {link.split('/')[-1]}")
                        continue
                except:
                    pass
                to_scrape.append((link, card_image, CITY))

            if not to_scrape:
                continue

            print(f"\n  🚀 Scraping {len(to_scrape)} restaurants with {WORKERS} workers...")

            # Process in batches using thread pool
            with ThreadPoolExecutor(max_workers=WORKERS) as executor:
                futures = {executor.submit(scrape_restaurant_worker, args): args for args in to_scrape}
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        if result:
                            with _save_lock:
                                total_saved += 1
                    except Exception as e:
                        print(f"    ✗ Worker error: {e}")

            print(f"\n  📊 Batch complete — saved: {total_saved}/{MAX_RESTAURANTS}")

            if total_saved >= MAX_RESTAURANTS:
                break

            # Delay before next scroll
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
    finally:
        try:
            driver.quit()
        except:
            pass

    print(f"\n{'='*60}")
    print(f"✅ Scraping complete!")
    print(f"   Total restaurants saved: {total_saved}")
    print(f"   Total skipped (already scraped): {total_skipped}")
    print(f"   Data location: data/{CITY}/restaurants/")