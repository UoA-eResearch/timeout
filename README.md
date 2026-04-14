[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/UoA-eResearch/timeout)

[![Google Search Scraper](https://github.com/UoA-eResearch/timeout/actions/workflows/googlesearch.yml/badge.svg)](https://github.com/UoA-eResearch/timeout/actions/workflows/googlesearch.yml)

### Installation

`uv pip install -r requirements.txt`  

To download videos, you can use the following command:

```bash
yt-dlp --write-info-json --batch-file timeout_links.txt --paths timeout_videos
```

or:

```bash
yt-dlp --write-info-json --batch-file supplements_links.txt --paths supplements_videos
```
