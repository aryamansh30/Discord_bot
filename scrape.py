import os, json, urllib.parse
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests

# load env from GitHub Actions secrets
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

# same pagination settings as before
AMAZON_PAGE_SIZE = 10
AMAZON_MAX_PAGES = 3
MICROSOFT_MAX_PAGES = 3
SEEN_FILE_TMPL = "seen_{}.json"

def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")

def get_driver():
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=opts)

def get_amazon_jobs():
    jobs = []
    for page in range(AMAZON_MAX_PAGES):
        offset = page * AMAZON_PAGE_SIZE
        url = (
            f"https://www.amazon.jobs/en-gb/search?"
            f"offset={offset}&result_limit={AMAZON_PAGE_SIZE}"
            f"&sort=recent&country%5B%5D=USA&base_query=software%20intern"
        )
        drv = get_driver()
        try:
            drv.get(url)
            elems = WebDriverWait(drv, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "h3.job-title a"))
            )
            for e in elems:
                title = e.text.strip()
                href  = e.get_attribute("href")
                link  = href if href.startswith("http") else "https://www.amazon.jobs" + href
                jobs.append({"title": title, "link": link})
        except Exception as e:
            log(f"❌ Amazon page {page+1} failed: {e}")
        finally:
            drv.quit()
    # remove duplicates
    return list({j['link']:j for j in jobs}.values())

# implement get_google_jobs() and get_microsoft_jobs() similarly,
# copying from your existing functions but returning a list of dicts.

SCRAPERS = {
    "amazon": get_amazon_jobs,
    "google":  get_google_jobs,
    "microsoft": get_microsoft_jobs,
}

def load_seen(name):
    path = SEEN_FILE_TMPL.format(name)
    if not os.path.exists(path): return set()
    return set(json.load(open(path)))

def save_seen(name, seen):
    with open(SEEN_FILE_TMPL.format(name), "w") as f:
        json.dump(list(seen), f)

def notify_discord(company, new_jobs):
    for job in new_jobs:
        content = f"🆕 **[{company.title()}]** {job['title']}\n{job['link']}"
        requests.post(
            DISCORD_WEBHOOK,
            json={"content": content},
            headers={"Content-Type": "application/json"},
            timeout=10
        )

def main():
    for name, scraper in SCRAPERS.items():
        log(f"🔍 Checking {name}")
        seen = load_seen(name)
        alljobs = scraper()
        log(f"   parsed {len(alljobs)} jobs")
        new = [j for j in alljobs if j["link"] not in seen]
        if new:
            log(f"   Found {len(new)} new")
            notify_discord(name, new)
            seen |= {j["link"] for j in new}
            save_seen(name, seen)
        else:
            log("   No new jobs")
    log("✅ Done")

if __name__ == "__main__":
    main()
