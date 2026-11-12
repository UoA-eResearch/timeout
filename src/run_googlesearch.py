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
# Date of this run, recorded as first_seen for newly found videos
TODAY = datetime.now().strftime("%Y-%m-%d")

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

def save_error_screenshot(driver, error_name, count_error=True):
    """Save a screenshot (and the page HTML) when an error occurs"""
    global errors
    if count_error:
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
    """Solve a reCAPTCHA if Google shows one. Returns True if a CAPTCHA was found (solved or not), as the page has then changed"""
    driver.implicitly_wait(0)
    found = False
    try:
        captcha_iframes = [
            iframe for iframe in driver.find_elements(By.TAG_NAME, "iframe")
            if "captcha" in (iframe.get_attribute("title") or "").lower()
        ]
        if captcha_iframes:
            found = True
            print("Solving recaptcha")
            solver = RecaptchaSolver(driver=driver)
            solver.click_recaptcha_v2(iframe=captcha_iframes[0])
            time.sleep(1)
        elif "/sorry/" in driver.current_url or driver.find_elements(By.CSS_SELECTOR, "form[id*=captcha]"):
            found = True
            print("Blocked by an unsolvable CAPTCHA")
    except Exception as e:
        print(f"Could not solve recaptcha: {e}")
    driver.implicitly_wait(10)
    return found

# Result card selectors: cards are normally wrapped in div.MjjYud, but pages loaded after a CAPTCHA
# leave most cards unwrapped, so also look for the card itself and use whichever finds more
RESULT_SELECTORS = ["div.MjjYud", "div.Z1YvVd"]

def find_results(driver):
    """Find the short video result cards on the page"""
    driver.implicitly_wait(0)
    results = max((driver.find_elements(By.CSS_SELECTOR, selector) for selector in RESULT_SELECTORS), key=len)
    driver.implicitly_wait(10)
    return results

def load_all_results(driver, url, max_scrolls=10):
    """Open a search and load all of its results, returning False if a CAPTCHA interrupted it"""
    print(url)
    driver.get(url)
    time.sleep(2)
    if check_and_solve_captcha(driver):
        return False

    # Scroll to load more results
    print(f"Scrolling to load more results...")
    for i in range(max_scrolls):
        ActionChains(driver).scroll_by_amount(0, 10000).perform()
        time.sleep(1)
        if check_and_solve_captcha(driver):
            return False

    # Click "More results" until there's no button, then scroll until no new results load
    # (some layouts load results by continuous scrolling instead of the button)
    print("Loading more results...")
    count = len(find_results(driver))
    for i in range(200):
        try:
            driver.find_element(By.LINK_TEXT, "More results").click()
            clicked = True
        except Exception:
            ActionChains(driver).scroll_by_amount(0, 10000).perform()
            clicked = False
        time.sleep(1.5)
        if check_and_solve_captcha(driver):
            return False
        new_count = len(find_results(driver))
        print(f"Results: {new_count}")
        if not clicked and new_count == count:
            break
        count = new_count
    print("No more results")
    return True

def search_and_scrape(driver, query, max_scrolls=10, region=None):
    """Search Google and scrape short video results, optionally localised to a country (e.g. "nz")"""
    print(f"\nSearching for: {query}")

    # Navigate to Google, starting again if a CAPTCHA interrupts loading (solving one redirects the page)
    url = f"https://www.google.com/search?udm=39&q={query}"
    if region:
        url += f"&gl={region}"
    for attempt in range(3):
        if load_all_results(driver, url, max_scrolls):
            break
        print("CAPTCHA interrupted the search, reloading")
    else:
        print("Search kept being interrupted by CAPTCHAs")
        return pd.DataFrame()

    # Get all results
    results = find_results(driver)
    print(f"\nTotal results found: {len(results)}")

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


def join_terms(values):
    """Combine "; "-separated lists of search terms, without repeats"""
    terms = sorted({t for v in values.dropna() for t in str(v).split("; ") if t})
    return "; ".join(terms) if terms else None


def scrape_dataset(driver, name, use_tor=False, retries=3, delay=30):
    """Run each of a dataset's search terms and merge the results into data/{name}.csv after each one.
    A term with no results is retried with a fresh browser after a growing wait (1, 2, 4... minutes), since that
    usually means Google is blocking us; if it still fails the dataset is abandoned.
    Returns (new, total) row counts and the driver, which may have been restarted"""
    search_terms = pd.read_table(f"data/{name}_search_terms.txt", header=None)[0].tolist()
    random.shuffle(search_terms)

    # Load old data if exists
    csv_path = f"data/{name}.csv"
    old_df = None
    if os.path.exists(csv_path):
        print("\nLoading previous results...")
        old_df = pd.read_csv(csv_path)
        # Retry any goto links that failed to resolve on a previous run
        old_df.link = old_df.link.map(strip_query).map(resolve_google_goto)
        print(f"Previous results: {len(old_df)} rows")

    dfs = []
    new, total = 0, 0 if old_df is None else len(old_df)
    for i, search_term in enumerate(search_terms, 1):
        if i > 1:
            # Pause between searches (randomised) to avoid looking automated
            pause = random.uniform(0.5, 1.5) * delay
            print(f"\nWaiting {pause:.0f}s before the next search...")
            time.sleep(pause)
        print(f"\nRunning search {i}/{len(search_terms)}: {search_term}")

        for attempt in range(1, retries + 1):
            df = search_and_scrape(driver, search_term, region=REGIONS.get(name))
            if not df.empty:
                break
            print(f"\nNo results found (attempt {attempt}/{retries}). Might be IP blocked or rate limited.")
            if attempt == retries:
                break
            save_error_screenshot(driver, f"no_results_{name}_attempt{attempt}", count_error=False)
            wait = 60 * 2 ** (attempt - 1)
            print(f"Restarting the browser and retrying in {wait}s...")
            driver.quit()
            time.sleep(wait)
            driver = start_driver(use_tor)

        if df.empty:
            print("Giving up. Try running with: torsocks python3 run_googlesearch.py")
            save_error_screenshot(driver, f"no_results_{name}")
            break

        print(f"\nResults from {search_term}: {len(df)} rows")
        print(df.source.value_counts())
        df["search_terms"] = search_term
        dfs.append(df)

        # Combine with old data, keeping the newly scraped row for links seen before, and save progress
        combined = pd.concat(dfs if old_df is None else dfs + [old_df], ignore_index=True)
        df = drop_duplicate_videos(combined)
        # Record every search term that has found each video, and the date it was first seen (blank for videos
        # found before this was recorded)
        keys, df_keys = combined.link.map(video_key), df.link.map(video_key)
        df["search_terms"] = df_keys.map(combined.groupby(keys)["search_terms"].agg(join_terms))
        old_first_seen = {} if old_df is None else dict(zip(
            old_df.link.map(video_key), old_df["first_seen"] if "first_seen" in old_df else [None] * len(old_df)))
        df["first_seen"] = [old_first_seen[k] if k in old_first_seen else TODAY for k in df_keys]
        df = df[df.source.isin(["Instagram", "TikTok", "YouTube", "Facebook"])].sort_values(by="link")
        new = len(df) if old_df is None else (~df.link.map(video_key).isin(old_df.link.map(video_key))).sum()
        total = len(df)
        print(f"Total unique results: {total} rows, new (after filtering): {new} rows")

        os.makedirs("data", exist_ok=True)
        df.to_csv(csv_path, index=False)
        df.link.drop_duplicates().to_csv(f"data/{name}_links.txt", index=False, header=False)
        print(f"Saved to: {csv_path} and data/{name}_links.txt")

    if not dfs:
        print(f"No new {name} data collected. Existing: {total} rows")
    return new, total, driver


def start_driver(use_tor=False):
    """Start a Chrome session (undetected-chromedriver) matching the installed Chrome version"""
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
    if use_tor:
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

    # Pass version_main to ensure ChromeDriver matches installed Chrome
    if chrome_version:
        driver = uc.Chrome(options=options, version_main=chrome_version, use_subprocess=False)
    else:
        # Fallback to auto-detection if version detection failed
        driver = uc.Chrome(options=options, use_subprocess=False)
    driver.implicitly_wait(10)
    driver.set_page_load_timeout(15)
    return driver


def main():
    """Main execution function"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Google Search Scraper for Menopause Supplements/Vitamins, Parenting Timeout and Youth Psychological Distress')
    parser.add_argument('--use-tor', action='store_true', help='Use Tor SOCKS proxy for scraping')
    parser.add_argument('--dataset', nargs='+', choices=DATASETS, default=DATASETS,
                        help='Dataset(s) to scrape for (default: all)')
    parser.add_argument('--retries', type=int, default=3,
                        help='Attempts per search term before giving up on a dataset, with a fresh browser and a growing wait between attempts (default: 3)')
    parser.add_argument('--delay', type=float, default=30,
                        help='Average seconds to wait between searches, randomised by +/-50%% (default: 30)')
    args = parser.parse_args()

    print("=" * 80)
    print("Google Search Scraper for Menopause Supplements/Vitamins, Parenting Timeout and Youth Psychological Distress")
    print(f"Datasets: {', '.join(args.dataset)}")
    if args.use_tor:
        print("Using Tor SOCKS proxy (localhost:9050)")
    print("=" * 80)

    # Add Tor proxy configuration if requested
    if args.use_tor:
        session.proxies = {"http": "socks5h://localhost:9050", "https": "socks5h://localhost:9050"}

    try:
        driver = start_driver(args.use_tor)
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
            new, total, driver = scrape_dataset(driver, name, args.use_tor, args.retries, args.delay)
            summary[name] = (new, total)

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
