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
    cards = driver.find_elements(By.CSS_SELECTOR, "div[class*='jumbo-tracker']")
    results = {}  # { url: card_image_url }
    for card in cards:
        a_tags = card.find_elements(By.TAG_NAME, "a")
        if len(a_tags) >= 2:
            href = a_tags[1].get_attribute("href") or ""
            if "/info" in href:
                url = href.replace("/info", "")
                # Grab the card thumbnail image (first img inside the card)
                card_img = "N/A"
                try:
                    img_el = card.find_element(By.TAG_NAME, "img")
                    src = img_el.get_attribute("src") or img_el.get_attribute("data-src") or ""
                    if src:
                        card_img = src
                except:
                    pass
                results[url] = card_img
    return results  # returns dict {url: card_image}


def scrape_menu_images(driver, url):
    """On the /info page, scroll to menu section, click each menu card
    to open popup, navigate pages with arrow, collect images."""
    menu_images = {}  # { "Food Menu": [img1, img2, ...], "Bar Menu": [...] }

    try:
        # Make sure we're on the info page
        info_url = url.rstrip("/") + "/info"
        if "/info" not in driver.current_url:
            driver.get(info_url)
            time.sleep(4)

        # Scroll down to make menu section visible
        driver.execute_script("window.scrollTo(0, 600);")
        time.sleep(2)

        # Find elements with "page" or "pages" text — these sit under the menu cards
        page_indicators = driver.find_elements(
            By.XPATH,
            "//*[contains(text(),' page')]"
        )

        menu_cards_info = []  # [(menu_name, clickable_element)]
        for indicator in page_indicators:
            try:
                text = indicator.text.strip().lower()
                if "page" not in text:
                    continue
                # The clickable card is typically a parent/grandparent of the "X pages" text
                parent = indicator.find_element(By.XPATH, "./..")
                grandparent = parent.find_element(By.XPATH, "./..")
                container_text = grandparent.text.strip()
                lines = [l.strip() for l in container_text.split("\n") if l.strip()]
                # Menu name is the line containing "Menu" but not "page"
                menu_name = "Menu"
                for line in lines:
                    if "menu" in line.lower() and "page" not in line.lower():
                        menu_name = line
                        break
                menu_cards_info.append((menu_name, grandparent))
            except:
                continue

        if not menu_cards_info:
            # Fallback: find menu thumbnail images and use their parent as clickable
            menu_section_imgs = driver.find_elements(
                By.XPATH,
                "//img[contains(@src,'zmtcdn.com') and contains(@src,'menu')]"
            )
            for idx, img in enumerate(menu_section_imgs):
                try:
                    parent = img.find_element(By.XPATH, "./..")
                    menu_cards_info.append((f"Menu {idx + 1}", parent))
                except:
                    pass

        print(f"      📋 Found {len(menu_cards_info)} menu(s) to scrape")

        for menu_name, card_element in menu_cards_info:
            try:
                print(f"      📖 Opening: {menu_name}")

                # Click the menu card to open popup
                driver.execute_script("arguments[0].click();", card_element)
                time.sleep(3)

                page_images = []
                seen_srcs = set()
                max_pages = 50

                for page_num in range(max_pages):
                    # Grab all large images currently visible in the popup
                    popup_imgs = driver.find_elements(
                        By.CSS_SELECTOR, "img[src*='zmtcdn.com']"
                    )

                    for img in popup_imgs:
                        src = img.get_attribute("src") or ""
                        if not src or src in seen_srcs:
                            continue
                        if ("zmtcdn.com" in src and "logo" not in src
                                and "icon" not in src and "/data/pictures" not in src
                                and "reviews_photos" not in src
                                and "res_card" not in src):
                            natural_w = driver.execute_script(
                                "return arguments[0].naturalWidth || arguments[0].offsetWidth || 0;", img
                            )
                            if natural_w > 300:
                                seen_srcs.add(src)
                                page_images.append(src)

                    # Click right arrow to go to next menu page
                    next_clicked = False
                    try:
                        # Find the right/next arrow in the popup
                        right_arrows = driver.find_elements(
                            By.CSS_SELECTOR,
                            "[class*='next'], [class*='right-arrow'], "
                            "[aria-label*='next' i], [aria-label*='Next']"
                        )

                        if not right_arrows:
                            # Look for clickable elements on the right side of the screen
                            candidates = driver.find_elements(
                                By.CSS_SELECTOR,
                                "div[role='button'], button, span[role='button']"
                            )
                            for el in candidates:
                                try:
                                    loc = el.location
                                    if loc['x'] > 900:  # Right side of 1920px window
                                        # Check if it contains an SVG or arrow-like content
                                        inner = el.get_attribute("innerHTML") or ""
                                        if "svg" in inner.lower() or "arrow" in inner.lower() or ">" in el.text:
                                            right_arrows.append(el)
                                except:
                                    pass

                        if right_arrows:
                            driver.execute_script("arguments[0].click();", right_arrows[0])
                            time.sleep(1.5)
                            next_clicked = True

                            # Check if a new image appeared
                            new_imgs = driver.find_elements(
                                By.CSS_SELECTOR, "img[src*='zmtcdn.com']"
                            )
                            has_new = False
                            for img in new_imgs:
                                src = img.get_attribute("src") or ""
                                if src and src not in seen_srcs and "zmtcdn.com" in src:
                                    has_new = True
                                    break
                            if not has_new:
                                break
                        else:
                            break
                    except:
                        break

                    if not next_clicked:
                        break

                if page_images:
                    menu_images[menu_name] = page_images
                    print(f"        ✓ {len(page_images)} page(s) collected")
                else:
                    print(f"        ✗ No pages collected")

                # Close the popup — click X or press Escape
                try:
                    close_btn = driver.find_elements(
                        By.CSS_SELECTOR,
                        "[class*='close'], [aria-label*='close' i], [aria-label*='Close']"
                    )
                    if close_btn:
                        driver.execute_script("arguments[0].click();", close_btn[0])
                    else:
                        from selenium.webdriver.common.keys import Keys
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(1.5)
                except:
                    from selenium.webdriver.common.keys import Keys
                    try:
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    except:
                        pass
                    time.sleep(1.5)

            except Exception as e:
                print(f"      ⚠️  Error with {menu_name}: {e}")
                try:
                    from selenium.webdriver.common.keys import Keys
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(1)
                except:
                    pass
                continue

    except Exception as e:
        print(f"      ⚠️  Error scraping menus: {e}")

    return menu_images


def scrape_restaurant_detail(driver, url, card_image="N/A"):
    info_url = url + "/info" if not url.endswith("/info") else url
    driver.get(info_url)
    time.sleep(3)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)

    data = {"url": url, "card_image": card_image}  # thumbnail from listing page
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

    # Menu images - click menu cards on info page, navigate popup pages
    data["menu_images"] = scrape_menu_images(driver, url)

    # Re-navigate to info page since popup interaction may have changed state
    driver.get(info_url)
    time.sleep(2)

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

    data["reviews_link"] = url + "/reviews"
    data["photos_link"] = url + "/photos"

    return data



def append_to_json(filepath, record):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = []
    existing.append(record)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

# ---- MAIN ----
if __name__ == "__main__":
    OUTPUT_FILE = os.getenv("OUTPUT_FILE")

    driver = get_driver()

    print("🌐 Loading Zomato Mumbai restaurants page...")
    driver.get(os.getenv("BASE_URL"))
    time.sleep(5)

    already_seen_links = set()
    total_saved = 0
    scroll_num = 0
    consecutive_empty = 0

    while True:
        scroll_num += 1
        print(f"\n{'='*60}")
        print(f"📜 Scroll {scroll_num} (total saved: {total_saved})...")

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        current_links = get_links_after_one_scroll(driver)
        new_links_dict = {url: img for url, img in current_links.items() if url not in already_seen_links}
        already_seen_links.update(new_links_dict.keys())

        print(f"  🔗 {len(new_links_dict)} new restaurant links found")

        if not new_links_dict:
            consecutive_empty += 1
            print(f"  ⚠️  No new links found ({consecutive_empty}/5)...")
            if consecutive_empty >= 5:
                print("  🏁 No more restaurants to scrape. Stopping.")
                break
            time.sleep(2)
            continue

        consecutive_empty = 0
        listing_url = driver.current_url
        new_links_list = list(new_links_dict.items())

        for i, (link, card_image) in enumerate(new_links_list, 1):
            print(f"\n  [{i}/{len(new_links_list)}] Scraping: {link}")
            try:
                data = scrape_restaurant_detail(driver, link, card_image)
                append_to_json(OUTPUT_FILE, data)
                total_saved += 1

                print(f"    ✓ {data['name']}")
                print(f"      Dining:     {data['dining_rating']}★ ({data['dining_rating_count']} ratings)")
                print(f"      Delivery:   {data['delivery_rating']}★ ({data['delivery_rating_count']} ratings)")
                print(f"      Cuisines:   {', '.join(data['cuisines'])}")
                print(f"      Top Dishes: {', '.join(data['top_dishes'])}")
                print(f"      Phone:      {', '.join(data['phone'])}")
                print(f"      Cost:       {data['cost_for_two']}")
                print(f"      Status:     {data['status']}")
                print(f"      Images:     {len(data['images'])}")
                menu_count = sum(len(v) for v in data['menu_images'].values())
                print(f"      Menu Imgs:  {menu_count} images across {len(data['menu_images'])} menus")
                print(f"      Direction:  {data['direction_link']}")
                print(f"      💾 Saved to {OUTPUT_FILE} (Total: {total_saved})")
            except Exception as e:
                print(f"    ✗ Error scraping {link}: {e}")
            time.sleep(1)
            break

        print(f"\n  🔄 Returning to listing page...")
        driver.get(listing_url)
        time.sleep(3)
        break

        print(f"  ⏩ Re-scrolling to position ({scroll_num} scrolls)...")
        for _ in range(scroll_num):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

    driver.quit()

    print(f"\n{'='*60}")
    print(f"✅ Scraping complete!")
    print(f"   Total restaurants saved: {total_saved}")
