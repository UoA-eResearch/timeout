#!/usr/bin/env python3
"""Test script to run googlesearch.ipynb logic"""

from tqdm.auto import tqdm
import os
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import time
import pandas as pd

def test_googlesearch():
    """Test if we can successfully scrape Google search results"""
    print("Starting Chrome driver...")

    # Configure Chrome options for headless mode
    options = uc.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')

    try:
        driver = uc.Chrome(options=options, headless=True, use_subprocess=False)
        driver.implicitly_wait(10)
        driver.set_page_load_timeout(15)

        print("Navigating to Google...")
        driver.get("https://www.google.com/")

        print("Searching for '#menopause #supplements'...")
        search_field = driver.find_element(By.TAG_NAME, "textarea")
        search_field.clear()
        search_field.send_keys("#menopause #supplements")
        search_field.submit()

        time.sleep(3)

        # Try to click on Short videos
        try:
            driver.find_element(By.LINK_TEXT, "Short videos").click()
            print("Clicked on 'Short videos'")
            time.sleep(2)
        except Exception as e:
            print(f"Could not find 'Short videos' link: {e}")
            # Try to get any results we can find

        # Try to get some results
        results = driver.find_elements(By.CSS_SELECTOR, "div.MjjYud")
        print(f"Found {len(results)} initial results")

        if len(results) == 0:
            print("No results found - might be IP blocked or different page structure")
            return False

        # Test parsing a few results
        parsed_results = []
        for i, result in enumerate(results[:5]):  # Just test first 5
            try:
                link = result.find_elements(By.TAG_NAME, "a")[0].get_attribute("href")
                bits = result.text.split("\n")
                if len(bits) >= 3:
                    duration = bits[0]
                    title = bits[1]
                    print(f"Result {i+1}: {title[:50]}...")
                    parsed_results.append({
                        "link": link,
                        "title": title
                    })
            except Exception as e:
                print(f"Error parsing result {i+1}: {e}")

        driver.quit()

        if len(parsed_results) > 0:
            print(f"\nSuccessfully parsed {len(parsed_results)} results!")
            print("Test PASSED - not IP blocked")
            return True
        else:
            print("\nFailed to parse any results")
            print("Test FAILED - might be IP blocked")
            return False

    except Exception as e:
        print(f"Error during test: {e}")
        try:
            driver.quit()
        except:
            pass
        return False

if __name__ == "__main__":
    success = test_googlesearch()
    exit(0 if success else 1)
