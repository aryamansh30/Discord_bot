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

def get_google_jobs():
    url = (
        "https://www.google.com/about/careers/applications/jobs/results/"
        "?q=Software%20Intern&location=United%20States"
        "&target_level=INTERN_AND_APPRENTICE&employment_type=INTERN"
        "&sort_by=date&degree=BACHELORS"
    )
    drv = get_driver()
    jobs = []
    try:
        drv.get(url)
        wait = WebDriverWait(drv, 10)
        cards = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.Ln1EL")))
        for card in cards:
            try:
                title = card.find_element(By.CSS_SELECTOR, "h3.QJPWVe").text.strip()
                link_elem = card.find_element(By.CSS_SELECTOR, "a.WpHeLc")
                href = link_elem.get_attribute("href")
                full_link = urllib.parse.urljoin(url, href)
                jobs.append({"title": title, "link": full_link})
            except Exception as e:
                log(f"⚠️ Google parsing card failed: {e}")
        return jobs
    except Exception as e:
        log(f"❌ Google scraping failed: {e}")
        return []
    finally:
        drv.quit()


def get_microsoft_jobs():
    jobs = []
    for page in range(1, MICROSOFT_MAX_PAGES + 1):
        url = (
            f"https://jobs.careers.microsoft.com/global/en/search?"
            f"q=Software&lc=United%20States&exp=Students%20and%20graduates&et=Internship"
            f"&l=en_us&pg={page}&pgSz=20&o=Relevance&flt=true"
        )
        drv = get_driver()
        try:
            drv.get(url)
            wait = WebDriverWait(drv, 10)
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.ms-List-cell")))
            cards = drv.find_elements(By.CSS_SELECTOR, "div.ms-List-cell")
            for card in cards:
                try:
                    title_elem = card.find_element(By.CSS_SELECTOR, "h2")
                    title = title_elem.text.strip()
                    # The old logic of clicking the 'See details' button is problematic in headless mode.
                    # Instead, we can construct the link directly.
                    job_id = card.get_attribute("data-automation-id")
                    link = f"https://jobs.careers.microsoft.com/global/en/job/{job_id}/"
                    jobs.append({"title": title, "link": link})
                except Exception as e:
                    log(f"⚠️ Microsoft parsing card failed: {e}")
        except Exception as e:
            log(f"❌ Microsoft scraping failed on page {page}: {e}")
        finally:
            drv.quit()
    # remove duplicates
    return list({j['link']:j for j in jobs}.values())

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
