#!/usr/bin/env python3
"""
Script to run the googlesearch notebook and save results.
This script replicates the googlesearch.ipynb notebook logic.
"""

from tqdm.auto import tqdm
import os
import sys
import argparse
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import time
import pandas as pd
from matplotlib_venn import venn2
import matplotlib.pyplot as plt

pd.set_option("display.max_colwidth", None)


def search_and_scrape(driver, query, max_scrolls=10):
    """Search Google and scrape short video results"""
    print(f"\nSearching for: {query}")

    # Navigate to Google
    driver.get("https://www.google.com/")
    time.sleep(2)

    # Search
    search_field = driver.find_element(By.TAG_NAME, "textarea")
    search_field.clear()
    search_field.send_keys(query)
    search_field.submit()
    time.sleep(3)

    # Click on Short videos if available
    try:
        driver.find_element(By.LINK_TEXT, "Short videos").click()
        print("Clicked on 'Short videos'")
        time.sleep(2)
    except Exception as e:
        print(f"Could not click 'Short videos': {e}")
        return pd.DataFrame()

    # Scroll to load more results
    print(f"Scrolling to load more results...")
    for i in range(max_scrolls):
        ActionChains(driver).scroll_by_amount(0, 10000).perform()
        time.sleep(1)

    # Click "More results" until no more available
    print("Loading more results...")
    while True:
        try:
            driver.find_element(By.LINK_TEXT, "More results").click()
            results_count = len(driver.find_elements(By.CSS_SELECTOR, "div.MjjYud"))
            print(f"Results: {results_count}")
            time.sleep(1.5)
        except Exception as e:
            print(f"No more results: {e}")
            break

    # Get all results
    results = driver.find_elements(By.CSS_SELECTOR, "div.MjjYud")
    print(f"\nTotal results found: {len(results)}")

    # Parse results
    parsed_results = []
    for result in tqdm(results, desc="Parsing results"):
        try:
            link = result.find_elements(By.TAG_NAME, "a")[0].get_attribute("href")
            bits = result.text.split("\n")
            duration = bits[0]
            title = bits[1]
            bits = bits[2].split()
            source = bits[0]
            author = bits[-1]
            parsed_results.append({
                "link": link,
                "duration": duration,
                "title": title,
                "source": source,
                "author": author,
            })
        except Exception as e:
            print(f"Error parsing result: {e}")
            continue

    return pd.DataFrame(parsed_results)


def main():
    """Main execution function"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Google Search Scraper for Menopause Supplements/Vitamins')
    parser.add_argument('--use-tor', action='store_true', help='Use Tor SOCKS proxy for scraping')
    args = parser.parse_args()

    print("=" * 80)
    print("Google Search Scraper for Menopause Supplements/Vitamins")
    if args.use_tor:
        print("Using Tor SOCKS proxy (localhost:9050)")
    print("=" * 80)

    # Configure Chrome options for headless mode
    options = uc.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')

    # Add Tor proxy configuration if requested
    if args.use_tor:
        options.add_argument('--proxy-server=socks5://localhost:9050')

    print("\nStarting Chrome driver...")
    try:
        driver = uc.Chrome(options=options, headless=True, use_subprocess=False)
        driver.implicitly_wait(10)
        driver.set_page_load_timeout(15)
    except Exception as e:
        print(f"Error starting Chrome: {e}")
        sys.exit(1)

    try:
        # Search for #menopause #supplements
        df1 = search_and_scrape(driver, "#menopause #supplements")

        if df1.empty:
            print("\nNo results found. Might be IP blocked or rate limited.")
            print("Try running with: torsocks python3 run_googlesearch.py")
            driver.quit()
            sys.exit(1)

        print(f"\nResults from '#menopause #supplements': {len(df1)} rows")
        print(df1.source.value_counts())

        # Search for #menopause #vitamins
        df2 = search_and_scrape(driver, "#menopause #vitamins")

        print(f"\nResults from '#menopause #vitamins': {len(df2)} rows")
        if not df2.empty:
            print(df2.source.value_counts())

        # Combine results
        print("\nCombining results...")
        df = pd.concat([df1, df2]).drop_duplicates()
        print(f"Combined unique results: {len(df)} rows")

        # Load old data if exists
        if os.path.exists("googlesearch.csv"):
            print("\nLoading previous results...")
            old_df = pd.read_csv("googlesearch.csv")
            print(f"Previous results: {len(old_df)} rows")

            # Show new results
            new_results = df[~df.link.isin(old_df.link)]
            print(f"New results: {len(new_results)} rows")

            # Combine with old data
            df = pd.concat([df, old_df]).drop_duplicates()
            print(f"Total unique results: {len(df)} rows")

        # Save results
        print("\nSaving results...")
        df.to_csv("supplements.csv", index=False)
        df.link.to_csv("supplements_links.txt", index=False, header=False)
        print("Saved to: supplements.csv and supplements_links.txt")

        print("\n" + "=" * 80)
        print("SUCCESS!")
        print("=" * 80)

    except Exception as e:
        print(f"\nError during execution: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
