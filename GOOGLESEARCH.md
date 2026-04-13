# Google Search Scraper Automation

This repository includes a GitHub Actions workflow that automatically scrapes Google search results for menopause-related supplements and vitamins.

## Files

- **`googlesearch.ipynb`**: Original Jupyter notebook with the scraping logic
- **`run_googlesearch.py`**: Python script version that can run in headless mode (used by GitHub Actions)
- **`.github/workflows/googlesearch.yml`**: GitHub Actions workflow for automated execution

## How It Works

The workflow:
1. Runs daily at 2 AM UTC (configurable via cron schedule)
2. Can also be triggered manually via GitHub Actions UI
3. Searches Google for:
   - `#menopause #supplements`
   - `#menopause #vitamins`
4. Scrapes short video results from the search
5. Combines results with previous data
6. Commits updated CSV files back to the repository

## IP Blocking Protection

The workflow includes protection against IP blocking:
1. First attempts to run without Tor
2. If that fails (likely due to IP blocking), automatically retries with Tor/torsocks
3. Tor provides anonymity and helps avoid rate limiting

## Output Files

- **`supplements.csv`**: Full results with columns: link, duration, title, source, author
- **`supplements_links.txt`**: Just the links, one per line

## Manual Execution

### Run the notebook locally:
```bash
jupyter notebook googlesearch.ipynb
```

### Run the Python script:
```bash
# Normal execution
python3 run_googlesearch.py

# With Tor (if IP blocked)
torsocks python3 run_googlesearch.py
```

### Trigger the GitHub Action manually:
1. Go to the "Actions" tab in GitHub
2. Select "Google Search Scraper" workflow
3. Click "Run workflow"

## Requirements

Python packages (see `requirements.txt`):
- pandas
- tqdm
- selenium
- undetected-chromedriver
- matplotlib-venn

System packages (for Tor support):
- tor
- torsocks
- chromium/chrome browser

## Customization

To change the search schedule, edit the cron expression in `.github/workflows/googlesearch.yml`:
```yaml
schedule:
  - cron: '0 2 * * *'  # Daily at 2 AM UTC
```

Common cron schedules:
- `0 */6 * * *` - Every 6 hours
- `0 0 * * 0` - Weekly on Sunday at midnight
- `0 0 1 * *` - Monthly on the 1st at midnight
