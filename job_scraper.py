from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

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
