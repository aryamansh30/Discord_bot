import os
import discord
import json
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from datetime import datetime
import urllib.parse

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

intents = discord.Intents.default()
client = discord.Client(intents=intents)
scheduler = AsyncIOScheduler()

# Pagination settings
AMAZON_PAGE_SIZE = 10
AMAZON_MAX_PAGES = 3
MICROSOFT_MAX_PAGES = 3

SEEN_FILE_TMPL = "seen_{}.json"

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

async def run_scraper(func):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func)


def get_amazon_job_titles():
    jobs = []
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    for page in range(AMAZON_MAX_PAGES):
        offset = page * AMAZON_PAGE_SIZE
        url = (
            f"https://www.amazon.jobs/en-gb/search?offset={offset}&result_limit={AMAZON_PAGE_SIZE}"
            f"&sort=recent&country%5B%5D=USA&base_query=software%20intern"
        )
        driver = webdriver.Chrome(options=options)
        try:
            driver.get(url)
            wait = WebDriverWait(driver, 10)
            elems = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "h3.job-title a")))
            if not elems:
                break
            for elem in elems:
                title = elem.text.strip()
                link = "https://www.amazon.jobs" + elem.get_attribute("href")
                jobs.append({"title": title, "link": link})
        except Exception as e:
            log(f"❌ Amazon scraping failed on page {page+1}: {e}")
        finally:
            driver.quit()
    unique = {j['link']: j for j in jobs}
    return list(unique.values())


def get_google_job_titles():
    url = (
        "https://www.google.com/about/careers/applications/jobs/results/"
        "?q=Software%20Intern&location=United%20States"
        "&target_level=INTERN_AND_APPRENTICE&employment_type=INTERN"
        "&sort_by=date&degree=BACHELORS"
    )
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    driver = webdriver.Chrome(options=options)
    jobs = []
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)
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
        driver.quit()


def get_microsoft_job_titles():
    jobs = []
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    for page in range(1, MICROSOFT_MAX_PAGES + 1):
        url = (
            f"https://jobs.careers.microsoft.com/global/en/search?"
            f"q=Software&lc=United%20States&exp=Students%20and%20graduates&et=Internship"
            f"&l=en_us&pg={page}&pgSz=20&o=Relevance&flt=true"
        )
        driver = webdriver.Chrome(options=options)
        try:
            driver.get(url)
            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.ms-List-cell")))
            cards = driver.find_elements(By.CSS_SELECTOR, "div.ms-List-cell")
            for card in cards:
                try:
                    title_elem = card.find_element(By.CSS_SELECTOR, "h2")
                    title = title_elem.text.strip()
                    see_btn = card.find_element(By.XPATH, ".//button[normalize-space()='See details']")
                    base_url = driver.current_url
                    driver.execute_script("arguments[0].scrollIntoView(true);", see_btn)
                    see_btn.click()
                    wait.until(EC.url_changes(base_url))
                    link = driver.current_url
                    jobs.append({"title": title, "link": link})
                    driver.back()
                    wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.ms-List-cell")))
                except Exception as e:
                    log(f"⚠️ Microsoft parsing card failed: {e}")
        except Exception as e:
            log(f"❌ Microsoft scraping failed on page {page}: {e}")
        finally:
            driver.quit()
    unique = {j['link']: j for j in jobs}
    return list(unique.values())


def load_seen_jobs(path):
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        try:
            return set(json.load(f))
        except json.JSONDecodeError:
            return set()


def save_seen_jobs(seen, path):
    with open(path, "w") as f:
        json.dump(list(seen), f)

async def check_and_post_jobs(company_name, scraper_func, seen_file):
    await client.wait_until_ready()
    log(f"🔍 Starting job check for {company_name}")

    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        log(f"❌ Could not find Discord channel with ID {CHANNEL_ID}")
        return

    jobs = await run_scraper(scraper_func)
    log(f"📄 Parsed {len(jobs)} jobs from {company_name}")

    seen = load_seen_jobs(seen_file)
    new_jobs = [job for job in jobs if job['link'] not in seen]

    if new_jobs:
        for job in new_jobs:
            await channel.send(f"🆕 [{company_name}] {job['title']} → {job['link']}")
        log(f"✅ Posted {len(new_jobs)} new jobs for {company_name}")
        seen.update(job['link'] for job in new_jobs)
        save_seen_jobs(seen, seen_file)
    else:
        log(f"⏳ No new jobs found for {company_name}")

    log(f"✅ Finished job check for {company_name}")
    print("--------------------------------------------------")

@client.event
async def on_ready():
    print(f"🤖 Logged in as {client.user}")

    # Schedule each scraper as its own concurrent job and start them immediately in separate tasks
    for name, func in [
        ("Amazon", get_amazon_job_titles),
        ("Google", get_google_job_titles),
        ("Microsoft", get_microsoft_job_titles)
    ]:
        seen_file = SEEN_FILE_TMPL.format(name.lower())
        interval = 3 if name == "Amazon" else (4 if name == "Google" else 5)
        # Allow up to 2 overlapping instances of this job
        scheduler.add_job(
            check_and_post_jobs,
            "interval",
            minutes=interval,
            args=[name, func, seen_file],
            max_instances=2
        )
        # Kick off the first run concurrently
        asyncio.create_task(check_and_post_jobs(name, func, seen_file))

    scheduler.start()

if __name__ == "__main__":
    client.run(TOKEN)
