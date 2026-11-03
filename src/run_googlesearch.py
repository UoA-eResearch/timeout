#!/usr/bin/env python3
"""
Script to run the googlesearch notebook and save results.
This script replicates the googlesearch.ipynb notebook logic.
"""

import random
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
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import requests
from selenium_recaptcha_solver import RecaptchaSolver

pd.set_option("display.max_colwidth", None)

# Datasets to scrape, each with its search terms in data/{name}_search_terms.txt
DATASETS = ["supplements", "timeout", "distress"]
# Google country code (gl parameter) to localise a dataset's search results to
REGIONS = {"distress": "nz"}

USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# HTTP session used to resolve Google redirect links without a browser
session = requests.Session()
session.headers["User-Agent"] = USER_AGENT


def update_readme_stats(datasets):
    """Update README.md with statistics for each dataset (a dict of name -> DataFrame)"""
    try:
        readme_path = "README.md"
        with open(readme_path, 'r') as f:
            content = f.read()

        # Prepare statistics
        dataset_stats = []
        for name, df in datasets.items():
            breakdown = df.source.value_counts().to_string().replace("source\n","").replace('\n', '\n- ')
            stats = f"""**{name.capitalize()} dataset:**
- Total videos: {len(df)}
- Breakdown by source:
- {breakdown}"""
            print(stats)
            dataset_stats.append(stats)
        all_stats = "\n\n".join(dataset_stats)

        stats_section = f"""## Dataset Statistics

{all_stats}

*Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}*

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

# Query parameters that identify the content (e.g. youtube.com/watch?v=...); all others are
# tracking/locale noise (hl, lang, si, xstg, utm_*, google_abuse...) that masks duplicate links
KEEP_QUERY_PARAMS = {"v", "story_fbid", "fbid", "id"}

def strip_query(url):
    """Remove query parameters that don't identify the content, so the same video always gets the same link"""
    if not isinstance(url, str) or "?" not in url:
        return url
    keep = {"url"} if url.startswith("https://www.google.com/goto?") else KEEP_QUERY_PARAMS
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k in keep])
    return urlunsplit(parts._replace(query=query))

def resolve_google_goto(url, retries=3):
    """Resolve a https://www.google.com/goto?url=... redirect link to its destination, returning the original URL if that fails"""
    if not isinstance(url, str) or not url.startswith("https://www.google.com/goto?"):
        return url
    for attempt in range(retries):
        try:
            response = session.get(url, allow_redirects=False, timeout=15)
            location = response.headers.get("location", "")
            if response.is_redirect and location.startswith("http") and "google.com/sorry" not in location:
                return strip_query(location)
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt)
    print(f"Could not resolve: {url}")
    return url

# Regexes extracting each platform's video ID, so different URL forms of the same video match
# (e.g. youtube /shorts/ID vs /watch?v=ID, instagram /p/ID/ vs /reel/ID/ vs /user/reel/ID/)
VIDEO_ID_PATTERNS = [
    ("youtube", r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/|embed/)|youtu\.be/)([\w-]{11})"),
    ("instagram", r"instagram\.com/(?:[\w.]+/)?(?:p|reels?|tv)/([\w-]+)"),
    ("tiktok", r"tiktok\.com/@[^/]*/(?:video|photo)/(\d+)"),
    ("facebook", r"facebook\.com/(?:.+/)?(?:videos|posts|reel)/(?:[^/]+/)?(\d+|pfbid\w+)/?$"),
    ("facebook", r"facebook\.com/watch/?\?(?:.*&)?v=(\d+)"),
]

def video_key(url):
    """Identify the video a link points to as platform:id, falling back to the link itself"""
    for platform, pattern in VIDEO_ID_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return f"{platform}:{match.group(1)}"
    return url

def drop_duplicate_videos(df):
    """Drop rows that are the same video, keeping the first www. link alphabetically so the choice is stable between runs
    (www. first because yt-dlp can't download secure./www-fallback. instagram links)"""
    df = df.drop_duplicates(subset="link", keep="first")
    df = df.assign(not_www=~df.link.str.startswith("https://www.")).sort_values(by=["not_www", "link"]).drop(columns="not_www")
    return df[~df.link.map(video_key).duplicated(keep="first")]


errors = 0

def save_error_screenshot(driver, error_name):
    """Save a screenshot when an error occurs"""
    global errors
    errors += 1
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"error-screenshot-{error_name}-{timestamp}.png"
        driver.save_screenshot(filename)
        with open(filename.replace(".png", ".html"), "w") as f:
            f.write(driver.page_source)

        print(f"Screenshot saved: {filename}")
    except Exception as e:
        print(f"Failed to save screenshot: {e}")

def check_and_solve_captcha(driver):
    driver.implicitly_wait(0)
    try:
        driver.find_element(By.CSS_SELECTOR, "form[id*=captcha]")
        raise ValueError("Unsolvable CAPTCHA found")
    except:
        pass
    try:
        captcha_iframe = [
            iframe for iframe in driver.find_elements(By.TAG_NAME, "iframe")
            if "captcha" in (iframe.get_attribute("title") or "").lower()
        ][0]
        print("Solving recaptcha")
        solver = RecaptchaSolver(driver=driver)
        solver.click_recaptcha_v2(iframe=captcha_iframe)
        time.sleep(1)
    except Exception as e:
        pass
    driver.implicitly_wait(10)
    return

def search_and_scrape(driver, query, max_scrolls=10, region=None):
    """Search Google and scrape short video results, optionally localised to a country (e.g. "nz")"""
    print(f"\nSearching for: {query}")
    solver = RecaptchaSolver(driver=driver)

    # Navigate to Google
    url = f"https://www.google.com/search?udm=39&q={query}"
    if region:
        url += f"&gl={region}"
    print(url)
    driver.get(url)
    time.sleep(2)
    check_and_solve_captcha(driver)

    # Scroll to load more results
    print(f"Scrolling to load more results...")
    for i in range(max_scrolls):
        ActionChains(driver).scroll_by_amount(0, 10000).perform()
        time.sleep(1)
        check_and_solve_captcha(driver)

    # Click "More results" until no more available
    print("Loading more results...")
    while True:
        try:
            driver.find_element(By.LINK_TEXT, "More results").click()
            results_count = len(driver.find_elements(By.CSS_SELECTOR, "div.MjjYud"))
            print(f"Results: {results_count}")
            time.sleep(1.5)
            check_and_solve_captcha(driver)
        except Exception as e:
            print(f"No more results")
            break

    # Get all results
    results = driver.find_elements(By.CSS_SELECTOR, "div.MjjYud")
    print(f"\nTotal results found: {len(results)}")
    check_and_solve_captcha(driver)

    # Parse results
    parsed_results = []
    for result in tqdm(results, desc="Parsing results"):
        try:
            link = resolve_google_goto(strip_query(result.find_elements(By.TAG_NAME, "a")[0].get_attribute("href")))
            bits = result.text.split("\n")

            # Ensure we have at least 3 elements in bits
            if len(bits) < 3:
                print(f"Skipping result with insufficient data: {bits}")
                #save_error_screenshot(driver, "insufficient_data")
                continue

            duration = bits[0]
            title = bits[1]
            source_info = bits[2].strip()

            # Ensure we have source information
            if not source_info:
                print(f"Skipping result with no source info")
                continue

            bits = source_info.split(" · ")
            if not bits[0].strip():
                print(f"Skipping result with empty source info")
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


def scrape_dataset(driver, name):
    """Run each of a dataset's search terms and merge the results into data/{name}.csv, returning (new, total) row counts"""
    search_terms = pd.read_table(f"data/{name}_search_terms.txt", header=None)[0].tolist()
    random.shuffle(search_terms)
    dfs = []
    for search_term in search_terms:
        print(f"\nRunning search for: {search_term}")
        df = search_and_scrape(driver, search_term, region=REGIONS.get(name))

        if df.empty:
            print("\nNo results found. Might be IP blocked or rate limited.")
            print("Try running with: torsocks python3 run_googlesearch.py")
            save_error_screenshot(driver, f"no_results_{name}")
            break

        print(f"\nResults from {search_term}: {len(df)} rows")
        print(df.source.value_counts())
        dfs.append(df)

    # Load old data if exists
    csv_path = f"data/{name}.csv"
    old_df = None
    if os.path.exists(csv_path):
        print("\nLoading previous results...")
        old_df = pd.read_csv(csv_path)
        # Retry any goto links that failed to resolve on a previous run
        old_df.link = old_df.link.map(strip_query).map(resolve_google_goto)
        print(f"Previous results: {len(old_df)} rows")

    if not dfs:
        total = 0 if old_df is None else len(old_df)
        print(f"No new {name} data collected. Existing: {total} rows")
        return 0, total

    # Combine with old data, keeping the newly scraped row for links seen before
    print("\nCombining results...")
    df = drop_duplicate_videos(pd.concat(dfs if old_df is None else dfs + [old_df]))
    df = df[df.source.isin(["Instagram", "TikTok", "YouTube", "Facebook"])].sort_values(by="link")
    new = len(df) if old_df is None else (~df.link.map(video_key).isin(old_df.link.map(video_key))).sum()
    print(f"Total unique results: {len(df)} rows, new (after filtering): {new} rows")

    os.makedirs("data", exist_ok=True)
    df.to_csv(csv_path, index=False)
    df.link.drop_duplicates().to_csv(f"data/{name}_links.txt", index=False, header=False)
    print(f"Saved to: {csv_path} and data/{name}_links.txt")
    return new, len(df)


def main():
    """Main execution function"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Google Search Scraper for Menopause Supplements/Vitamins, Parenting Timeout and Youth Psychological Distress')
    parser.add_argument('--use-tor', action='store_true', help='Use Tor SOCKS proxy for scraping')
    parser.add_argument('--dataset', nargs='+', choices=DATASETS, default=DATASETS,
                        help='Dataset(s) to scrape for (default: all)')
    args = parser.parse_args()

    print("=" * 80)
    print("Google Search Scraper for Menopause Supplements/Vitamins, Parenting Timeout and Youth Psychological Distress")
    print(f"Datasets: {', '.join(args.dataset)}")
    if args.use_tor:
        print("Using Tor SOCKS proxy (localhost:9050)")
    print("=" * 80)

    # Configure Chrome options for headless mode
    options = uc.ChromeOptions()
    #options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument(f'--user-agent={USER_AGENT}')

    # Add Tor proxy configuration if requested
    if args.use_tor:
        options.add_argument('--proxy-server=socks5://localhost:9050')
        session.proxies = {"http": "socks5h://localhost:9050", "https": "socks5h://localhost:9050"}

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
        # Track new/total results for the commit message
        summary = {}
        for name in args.dataset:
            print("\n" + "=" * 80)
            print(f"Starting {name} collection...")
            print("=" * 80)
            summary[name] = scrape_dataset(driver, name)

        # Update README with dataset statistics
        update_readme_stats({name: pd.read_csv(f"data/{name}.csv") for name in DATASETS if os.path.exists(f"data/{name}.csv")})

        print("\n" + "=" * 80)
        print("SUCCESS!")
        print("=" * 80)

        # Output summary for GitHub Actions to use in commit message
        print("\n" + "=" * 80)
        print("SUMMARY FOR COMMIT MESSAGE:")
        for name, (new, total) in summary.items():
            print(f"{name.capitalize()}: +{new} new, {total} total")
        print("=" * 80)

        print(f"Total errors encountered: {errors}")
        if errors > 0:
            sys.exit(1)

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
