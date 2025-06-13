import os
import discord
import json
from dotenv import load_dotenv
from job_scraper import get_amazon_job_titles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
SEEN_JOBS_FILE = "seen_jobs.json"

intents = discord.Intents.default()
client = discord.Client(intents=intents)
scheduler = AsyncIOScheduler()

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
