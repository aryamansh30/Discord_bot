import os
import discord
import json
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time


load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
SEEN_JOBS_FILE = "seen_jobs.json"

intents = discord.Intents.default()
client = discord.Client(intents=intents)
scheduler = AsyncIOScheduler()

def get_amazon_job_titles():
    url = "https://www.amazon.jobs/en-gb/search?offset=0&result_limit=10&sort=recent&country%5B%5D=USA&distanceType=Mi&radius=24km&latitude=38.89036&longitude=-77.03196&loc_group_id=&loc_query=united%20states&base_query=software%20intern&city=&country=USA&region=&county=&query_options=&"

    options = Options()
    options.add_argument("--headless")  # Run in headless mode (no UI)
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    driver = webdriver.Chrome(options=options)
    driver.get(url)

    time.sleep(3)  # Wait for JS to render (you can also use WebDriverWait)

    job_elements = driver.find_elements(By.CSS_SELECTOR, "h3.job-title a")
    jobs = []

    for elem in job_elements:
        title = elem.text.strip()
        link = "https://www.amazon.jobs" + elem.get_attribute("href")
        jobs.append({"title": title, "link": link})

    driver.quit()
    return jobs





def load_seen_jobs():
    if not os.path.exists(SEEN_JOBS_FILE):
        return set()
    with open(SEEN_JOBS_FILE, "r") as f:
        return set(json.load(f))

def save_seen_jobs(seen):
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump(list(seen), f)

async def check_and_post_jobs():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"Could not find channel with ID {CHANNEL_ID}")
        return

    jobs = get_amazon_job_titles()
    seen = load_seen_jobs()
    new_jobs = [job for job in jobs if job['link'] not in seen]

    if new_jobs:
        for job in new_jobs:
            await channel.send(f"🆕 {job['title']} → {job['link']}")
        print(f"Posted {len(new_jobs)} new jobs to Discord.")
        seen.update(job['link'] for job in new_jobs)
        save_seen_jobs(seen)
    else:
        print("No new jobs found.")

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    scheduler.add_job(check_and_post_jobs, "interval", minutes=5)
    scheduler.start()

if __name__ == "__main__":
    client.run(TOKEN)
