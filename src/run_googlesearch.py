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
from selenium.webdriver.common.action_chains import ActionChains
import time
import pandas as pd
from datetime import datetime
import shutil
import subprocess
import re

pd.set_option("display.max_colwidth", None)


def update_readme_stats(supplements_df, timeout_df):
    """Update README.md with dataset statistics"""
    try:
        readme_path = "README.md"
        with open(readme_path, 'r') as f:
            content = f.read()

        # Prepare statistics
        supplements_breakdown = supplements_df.source.value_counts().to_string().replace('\n', '\n  - ')
        supplements_stats = f"""**Supplements dataset:**
- Total videos: {len(supplements_df)}
- Breakdown by source:
  - {supplements_breakdown}"""

        timeout_breakdown = timeout_df.source.value_counts().to_string().replace('\n', '\n  - ')
        timeout_stats = f"""**Timeout dataset:**
- Total videos: {len(timeout_df)}
- Breakdown by source:
  - {timeout_breakdown}"""

        stats_section = f"""## Dataset Statistics

{supplements_stats}

{timeout_stats}

*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}*

"""

        # Find where to insert or replace stats
        # Look for existing Dataset Statistics section
        import re
        pattern = r'## Dataset Statistics\n.*?(?=\n## |\Z)'

        if re.search(pattern, content, re.DOTALL):
            # Replace existing section
            content = re.sub(pattern, stats_section.rstrip() + '\n\n', content, flags=re.DOTALL)
        else:
            # Insert before Repository Structure section or at the end
            if '## Repository Structure' in content:
                content = content.replace('## Repository Structure', stats_section + '## Repository Structure')
            else:
                # Insert before License section
                if '## License' in content:
                    content = content.replace('## License', stats_section + '## License')
                else:
                    content += '\n' + stats_section

        with open(readme_path, 'w') as f:
            f.write(content)

        print(f"\nUpdated README.md with dataset statistics")

    except Exception as e:
        print(f"Warning: Could not update README.md: {e}")


def save_error_screenshot(driver, error_name):
    """Save a screenshot when an error occurs"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"error-screenshot-{error_name}-{timestamp}.png"
        driver.save_screenshot(filename)
        print(f"Screenshot saved: {filename}")
    except Exception as e:
        print(f"Failed to save screenshot: {e}")


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
        save_error_screenshot(driver, "short_videos_not_found")
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
            print(f"No more results")
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

            # Ensure we have at least 3 elements in bits
            if len(bits) < 3:
                print(f"Skipping result with insufficient data: {bits}")
                continue

            duration = bits[0]
            title = bits[1]
            bits = bits[2].split(" · ")

            # Ensure we have source information
            if len(bits) == 0:
                print(f"Skipping result with no source info")
                continue

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
    parser = argparse.ArgumentParser(description='Google Search Scraper for Menopause Supplements/Vitamins and Parenting Timeout')
    parser.add_argument('--use-tor', action='store_true', help='Use Tor SOCKS proxy for scraping')
    args = parser.parse_args()

    print("=" * 80)
    print("Google Search Scraper for Menopause Supplements/Vitamins and Parenting Timeout")
    if args.use_tor:
        print("Using Tor SOCKS proxy (localhost:9050)")
    print("=" * 80)

    # Variables to track new results for commit message
    supplements_new = 0
    supplements_total = 0
    timeout_new = 0
    timeout_total = 0

    # Configure Chrome options for headless mode
    options = uc.ChromeOptions()
    #options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    # Add Tor proxy configuration if requested
    if args.use_tor:
        options.add_argument('--proxy-server=socks5://localhost:9050')

    print("\nStarting Chrome driver...")

    # Detect Chrome version
    chrome_version = None
    chrome_path = shutil.which("google-chrome") or shutil.which("chrome")
    if chrome_path:
        try:
            version_output = subprocess.check_output(
                [chrome_path, "--version"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            # Parse version like "Google Chrome 146.0.7680.0" -> 146
            match = re.search(r"(\d+)\.", version_output)
            if match:
                chrome_version = int(match.group(1))
                print(f"Detected Chrome version: {chrome_version}")
        except Exception as e:
            print(f"Could not detect Chrome version: {e}")

    try:
        # Pass version_main to ensure ChromeDriver matches installed Chrome
        if chrome_version:
            driver = uc.Chrome(options=options, version_main=chrome_version, use_subprocess=False)
        else:
            # Fallback to auto-detection if version detection failed
            driver = uc.Chrome(options=options, use_subprocess=False)
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
            save_error_screenshot(driver, "no_results_first_search")
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
        df = pd.concat([df1, df2]).drop_duplicates(subset="link", keep="first")
        print(f"Combined unique results: {len(df)} rows")

        # Load old data if exists
        if os.path.exists("data/supplements.csv"):
            print("\nLoading previous results...")
            old_df = pd.read_csv("data/supplements.csv")
            print(f"Previous results: {len(old_df)} rows")

            # Show new results
            new_results = df[~df.link.isin(old_df.link)]
            print(f"New results: {len(new_results)} rows")
            supplements_new = len(new_results)

            # Combine with old data
            df = pd.concat([df, old_df]).drop_duplicates(subset="link", keep="first")
            print(f"Total unique results: {len(df)} rows")
        else:
            # If no old data exists, all results are new
            supplements_new = len(df)

        # Save results
        print("\nSaving results...")
        df.sort_values(by="link", inplace=True)
        df = df[df.source.isin(["Instagram", "TikTok", "YouTube", "Facebook"])]
        supplements_total = len(df)
        os.makedirs("data", exist_ok=True)
        df.to_csv("data/supplements.csv", index=False)
        df.link.drop_duplicates().to_csv("data/supplements_links.txt", index=False, header=False)
        print("Saved to: data/supplements.csv and data/supplements_links.txt")

        # Now collect timeout data
        print("\n" + "=" * 80)
        print("Starting timeout collection...")
        print("=" * 80)

        # Search for #parenting #timeout
        df_timeout1 = search_and_scrape(driver, "#parenting #timeout")

        if df_timeout1.empty:
            print("\nNo results found for #parenting #timeout. Might be IP blocked or rate limited.")
            save_error_screenshot(driver, "no_results_timeout_first_search")
        else:
            print(f"\nResults from '#parenting #timeout': {len(df_timeout1)} rows")
            print(df_timeout1.source.value_counts())

        # Search for #gentleparenting #timeout
        df_timeout2 = search_and_scrape(driver, "#gentleparenting #timeout")

        if df_timeout2.empty:
            print("\nNo results found for #gentleparenting #timeout.")
        else:
            print(f"\nResults from '#gentleparenting #timeout': {len(df_timeout2)} rows")
            print(df_timeout2.source.value_counts())

        # Combine timeout results
        if not df_timeout1.empty or not df_timeout2.empty:
            print("\nCombining timeout results...")
            df_timeout = pd.concat([df_timeout1, df_timeout2]).drop_duplicates(subset="link", keep="first")
            print(f"Combined unique timeout results: {len(df_timeout)} rows")

            # Load old timeout data if exists
            if os.path.exists("data/timeout.csv"):
                print("\nLoading previous timeout results...")
                old_df_timeout = pd.read_csv("data/timeout.csv")
                print(f"Previous timeout results: {len(old_df_timeout)} rows")

                # Show new timeout results
                new_timeout_results = df_timeout[~df_timeout.link.isin(old_df_timeout.link)]
                print(f"New timeout results: {len(new_timeout_results)} rows")
                timeout_new = len(new_timeout_results)

                # Combine with old data
                df_timeout = pd.concat([df_timeout, old_df_timeout]).drop_duplicates(subset="link", keep="first")
                print(f"Total unique timeout results: {len(df_timeout)} rows")
            else:
                # If no old data exists, all results are new
                timeout_new = len(df_timeout)

            # Save timeout results
            print("\nSaving timeout results...")
            df_timeout.sort_values(by="link", inplace=True)
            df_timeout = df_timeout[df_timeout.source.isin(["Instagram", "TikTok", "YouTube", "Facebook"])]
            timeout_total = len(df_timeout)
            os.makedirs("data", exist_ok=True)
            df_timeout.to_csv("data/timeout.csv", index=False)
            df_timeout.link.drop_duplicates().to_csv("data/timeout_links.txt", index=False, header=False)
            print("Saved to: data/timeout.csv and data/timeout_links.txt")

        # Update README with dataset statistics
        if os.path.exists("data/supplements.csv") and os.path.exists("data/timeout.csv"):
            supplements_final = pd.read_csv("data/supplements.csv")
            timeout_final = pd.read_csv("data/timeout.csv")
            update_readme_stats(supplements_final, timeout_final)

        print("\n" + "=" * 80)
        print("SUCCESS!")
        print("=" * 80)

        # Output summary for GitHub Actions to use in commit message
        print("\n" + "=" * 80)
        print("SUMMARY FOR COMMIT MESSAGE:")
        print(f"Supplements: +{supplements_new} new, {supplements_total} total")
        print(f"Timeout: +{timeout_new} new, {timeout_total} total")
        print("=" * 80)

    except Exception as e:
        print(f"\nError during execution: {e}")
        import traceback
        traceback.print_exc()
        save_error_screenshot(driver, "general_error")
        sys.exit(1)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
