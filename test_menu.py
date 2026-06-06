"""Quick test: scrape menu images from Rasoi Dadar East"""
from zomato_scraper import get_driver, scrape_menu_images
import json

driver = get_driver()

try:
    url = "https://www.zomato.com/mumbai/rasoi-dadar-east"
    print(f"🔍 Testing menu scrape for: {url}")
    
    # Navigate to info page first
    driver.get(url + "/info")
    import time
    time.sleep(4)
    
    result = scrape_menu_images(driver, url)
    
    print(f"\n{'='*60}")
    print(f"📋 Result:")
    print(json.dumps(result, indent=2))
    print(f"\nTotal menus: {len(result)}")
    total_pages = sum(len(v) for v in result.values())
    print(f"Total menu pages: {total_pages}")
finally:
    driver.quit()
