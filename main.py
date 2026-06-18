import os
import discord
import json
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
import re
from datetime import datetime

from selenium.common.exceptions import TimeoutException, NoSuchElementException
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

    url = "https://www.amazon.jobs/content/en/career-programs/university?country%5B%5D=US"
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 15)
        # Wait for job cards to appear
        cards = wait.until(EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, "div.job-card-module_root__QYXVA")
        ))

        for card in cards:
            try:
                # Title and link
                title_elem = card.find_element(By.CSS_SELECTOR, "h3 a.header-module_title__9-W3R")
                title = title_elem.get_attribute("aria-label").strip()
                link = "https://www.amazon.jobs" + title_elem.get_attribute("href")

                # Location
                loc_elem = card.find_element(By.XPATH, ".//div[contains(@class, 'metadatum-module_text__ncKFr') and contains(text(), ', USA')]")
                location = loc_elem.text.strip() if loc_elem else ""

                # Date (optional, if present)
                date_elem = card.find_elements(By.XPATH, ".//div[contains(@class, 'metadatum-module_text__ncKFr') and contains(text(), 'Updated:')]")
                date_str = date_elem[0].text.strip() if date_elem else ""
                # You can parse the date if needed

                jobs.append({
                    "title": f"{title} – {location}" if location else title,
                    "link": link,
                    "date": date_str
                })
            except Exception as e:
                log(f"⚠️ Amazon parsing card failed: {repr(e)}")
    except Exception as e:
        log(f"❌ Amazon scraping failed: {repr(e)}")
    finally:
        driver.quit()

    # Deduplicate
    unique = {j['link']: j for j in jobs}
    return list(unique.values())

def get_netflix_job_titles():
    """
    Scrapes Netflix careers for US-based *intern* roles.
    It opens each result card to discover a stable job link from the detail panel.
    Returns: list of dicts with keys: title, link, date (date is optional/blank here).
    """
    jobs = []
    base_url = ("https://explore.jobs.netflix.net/careers"
                "?query=intern&location=United%20States"
                "&pid=790311778393&domain=netflix.com"
                "&sort_by=relevance&triggerGoButton=true")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 20)

    def scroll_results_container():
        # Try to progressively scroll the results list to load more cards (if virtualized)
        try:
            lst = driver.find_element(By.CSS_SELECTOR, "div[role='list']")
        except NoSuchElementException:
            return
        last = 0
        for _ in range(8):  # a few scroll passes
            cards = lst.find_elements(By.CSS_SELECTOR, "div[role='button'].position-card")
            count = len(cards)
            if count <= last:
                break
            last = count
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", lst)
            # small wait for virtualization to render
            WebDriverWait(driver, 5).until(
                lambda d: len(lst.find_elements(By.CSS_SELECTOR, "div[role='button'].position-card")) >= last
            )

    try:
        driver.get(base_url)

        # Wait for the list container & at least one result card
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='list']")))
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='button'].position-card")))

        # Try to load more results if the list is virtualized
        scroll_results_container()

        # Collect visible cards
        cards = driver.find_elements(By.CSS_SELECTOR, "div[role='button'].position-card")
        log(f"🔎 Netflix: found {len(cards)} cards in the results list")

        for idx, card in enumerate(cards):
            try:
                # Title prefer aria-label (e.g., 'Software Engineer Intern, …')
                title = card.get_attribute("aria-label") or ""
                if not title:
                    # fallback to inner title div
                    try:
                        title = card.find_element(By.CSS_SELECTOR, ".position-title").text.strip()
                    except NoSuchElementException:
                        title = ""

                # Only keep likely internship roles
                if "intern" not in title.lower():
                    continue

                # Location text
                location = ""
                try:
                    location = card.find_element(By.CSS_SELECTOR, ".position-location").text.strip()
                except NoSuchElementException:
                    pass

                # Open the card to load details pane (some UIs select the card without nav)
                driver.execute_script("arguments[0].click();", card)

                # Give the right pane time to hydrate; look for any outbound job link
                # Heuristics: jobs.netflix.com/jobs/<id> OR /job/… OR an "Apply" / "View" anchor
                link = None
                for _ in range(2):  # two short attempts (initial + after a slight pause)
                    try:
                        # common anchors we can use
                        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
                        candidates = []
                        for a in anchors:
                            href = a.get_attribute("href") or ""
                            text = (a.text or "").lower()
                            if any(s in href for s in [
                                "jobs.netflix.com/jobs",        # canonical job links
                                "/jobs/", "/job/", "workday",   # fallback patterns
                            ]) or any(t in text for t in ["apply", "view job", "view role"]):
                                candidates.append(href)

                        # Prefer canonical Netflix job links if present
                        primaries = [h for h in candidates if "jobs.netflix.com" in h and "/jobs/" in h]
                        if primaries:
                            link = primaries[0]
                            break
                        # else, pick first reasonable candidate
                        if candidates:
                            link = candidates[0]
                            break
                    except Exception:
                        pass
                    # tiny pause and retry to let UI finish rendering
                    WebDriverWait(driver, 2).until(lambda d: True)

                # As a last resort, try the current URL (the app sometimes updates it with position context)
                if not link:
                    current = driver.current_url
                    if "careers" in current:
                        link = current

                if not link:
                    log(f"⚠️ Netflix: no link found for card index {idx} ('{title}') — skipping")
                    continue

                jobs.append({
                    "title": f"{title}" + (f" – {location}" if location else ""),
                    "link": link,
                    "date": ""  # Date not readily exposed in list; leave blank
                })

            except Exception as e:
                log(f"⚠️ Netflix parsing card failed: {type(e).__name__}(): {e}")

        # Deduplicate by link
        return list({j["link"]: j for j in jobs}.values())

    except TimeoutException as e:
        log(f"❌ Netflix scraping timed out: {e}")
        return []
    except Exception as e:
        log(f"❌ Netflix scraping failed: {repr(e)}")
        return []
    finally:
        driver.quit()


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
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,1000")
    # Spoof UA a bit to reduce anti-bot quirks
    options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 20)

    def load_page(page):
        url = (
            "https://jobs.careers.microsoft.com/global/en/search?"
            "q=intern&lc=United%20States&exp=Students%20and%20graduates&et=Internship"
            f"&l=en_us&pg={page}&pgSz=20&o=Relevance&flt=true"
        )
        driver.get(url)
        # Wait for at least one list item to mount
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.ms-List-cell[role='listitem']")))
        # Lazy-load: scroll until no growth or a few iterations
        last_count = 0
        for _ in range(6):  # up to ~6 scroll cycles
            cells = driver.find_elements(By.CSS_SELECTOR, "div.ms-List-cell[role='listitem']")
            if len(cells) <= last_count:
                break
            last_count = len(cells)
            driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")
            # a short wait to let more rows render
            WebDriverWait(driver, 5).until(lambda d: len(
                d.find_elements(By.CSS_SELECTOR, "div.ms-List-cell[role='listitem']")
            ) >= last_count)

        return driver.find_elements(By.CSS_SELECTOR, "div.ms-List-cell[role='listitem']")

    try:
        for page in range(1, MICROSOFT_MAX_PAGES + 1):
            try:
                cells = load_page(page)
            except TimeoutException:
                log(f"❌ Microsoft page {page}: list items did not render in time")
                continue

            for cell in cells:
                try:
                    # The card wrapper that carries the stable aria-label: "Job item 1857312"
                    job_wrapper = cell.find_element(By.CSS_SELECTOR, "div[aria-label^='Job item']")
                    aria = job_wrapper.get_attribute("aria-label") or ""

                    m = re.search(r"Job item\s+(\d+)", aria)
                    if not m:
                        # Secondary fallback: look for any 6–9 digit id within descendant attributes
                        inner_html = cell.get_attribute("outerHTML")
                        m = re.search(r"\b(\d{6,9})\b", inner_html)
                    if not m:
                        raise NoSuchElementException("job id not found")

                    job_id = m.group(1)

                    # Title: any <h2> inside the listitem
                    title_el = cell.find_element(By.XPATH, ".//h2")
                    title = title_el.text.strip()

                    # Location: best-effort—find a span likely holding location
                    loc = ""
                    loc_elts = cell.find_elements(
                        By.XPATH,
                        ".//span[contains(., 'United States') or contains(., ', ')]"
                    )
                    for s in loc_elts:
                        t = s.text.strip()
                        # avoid obviously non-location spans (too long / empty)
                        if t and len(t) < 120 and any(k in t for k in ["United States", ", "]):
                            loc = t
                            break

                    link = f"https://jobs.careers.microsoft.com/global/en/job/{job_id}"
                    jobs.append({"title": f"{title}" + (f" – {loc}" if loc else ""), "link": link})

                except Exception as e:
                    log(f"⚠️ Microsoft parsing card failed: {type(e).__name__}()")

        # de-dup
        return list({j["link"]: j for j in jobs}.values())

    finally:
        driver.quit()


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

    for name, func in [
        ("Amazon", get_amazon_job_titles),
        ("Google", get_google_job_titles),
        ("Microsoft", get_microsoft_job_titles),
        ("Netflix", get_netflix_job_titles),   # ← added
    ]:
        seen_file = SEEN_FILE_TMPL.format(name.lower())
        # staggered intervals to avoid synchronized bursts
        interval = 3 if name == "Amazon" else (4 if name == "Google" else (5 if name == "Microsoft" else 6))
        scheduler.add_job(
            check_and_post_jobs,
            "interval",
            minutes=interval,
            args=[name, func, seen_file],
            max_instances=2
        )
        asyncio.create_task(check_and_post_jobs(name, func, seen_file))

    scheduler.start()


if __name__ == "__main__":
    client.run(TOKEN)
