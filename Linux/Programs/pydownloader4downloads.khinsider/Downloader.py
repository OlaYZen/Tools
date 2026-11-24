import os
import requests
import multiprocessing
from bs4 import BeautifulSoup
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import aiohttp
import asyncio
import configparser

config = configparser.ConfigParser()
config.read('settings.ini')

MAX_RETRIES = int(config['Retries'].get('max_retries', fallback=2))

url = input("Enter the URL: ")

# Fetch HTML content from the specified URL with proper headers
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive'
}
response = requests.get(url, headers=headers)
html_content = response.text

# Parse the HTML content
soup = BeautifulSoup(html_content, 'lxml')

# Find all elements with class 'playlistDownloadSong'
elements = soup.find_all(class_='playlistDownloadSong')

# Store URLs in a list
urls = []
for index, element in enumerate(elements):
    link = element.find('a')
    if link:
        url = link.get('href')
        full_url = f'https://downloads.khinsider.com{url}'
        urls.append(full_url)

# List to store failed URLs
failed_urls = []

# Lock to prevent concurrent printing of error messages
print_lock = asyncio.Lock()

# Function to fetch HTML content asynchronously
async def async_get_html_content(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                return await response.text()
    except aiohttp.ClientError as e:
        return None

# Function to find and save FLAC, MP3, or M4A URLs and album name
def find_audio_urls_and_album_name(html_content, priority_order):
    audio_urls = []
    album_name = None

    if html_content:
        soup = BeautifulSoup(html_content, "html.parser")

        # Find all links in the page
        links = soup.find_all("a", href=True)

        for file_type in priority_order:
            for link in links:
                href = link.get("href")
                if href.endswith(f".{file_type}"):
                    audio_urls.append(href)

            if audio_urls:
                break  # If any URLs are found for the current file type, break the loop

        # Extract album name
        album_name_element = soup.select_one("#pageContent > p:nth-child(6) > b:nth-child(1)")
        if album_name_element:
            album_name = album_name_element.text.strip()

    return audio_urls, album_name

# Function to download a file asynchronously with retry
async def async_download_audio_file(session, url, directory, total_progress):
    retries = 0

    while retries <= MAX_RETRIES:
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                content = await response.read()

                filename = unquote(os.path.join(directory, os.path.basename(url)))

                with open(filename, 'wb') as file:
                    file.write(content)

                total_progress.update(1)
                break  # Break the loop if download is successful
        except Exception as e:
            retries += 1
            if retries <= MAX_RETRIES:
                await asyncio.sleep(2)  # Wait for a moment before retrying
            else:
                async with print_lock:
                    failed_urls.append(url)
                break  # Break the loop if max retries reached

# Function to process a single URL asynchronously
async def async_process_url(session, url, total_progress, priority_order, download_path):
    html_content = await async_get_html_content(url)
    audio_urls, album_name = find_audio_urls_and_album_name(html_content, priority_order)

    if audio_urls and album_name:
        illegal_characters = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        sanitized_album_name = "".join(c if c.isalnum() or c not in illegal_characters else ' ' for c in album_name)

        # Use custom download path if provided, otherwise default to 'Audio files'
        if download_path:
            album_directory = os.path.join(download_path, sanitized_album_name)
        else:
            script_directory = os.path.dirname(os.path.realpath(__file__))
            album_directory = os.path.join(script_directory, 'Audio files', sanitized_album_name)

        os.makedirs(album_directory, exist_ok=True)

        for audio_url in audio_urls:
            await async_download_audio_file(session, audio_url, album_directory, total_progress)
    else:
        pass  # No audio files found for the URL

def get_cpu_threads():
    try:
        num_threads = os.cpu_count() or 1
    except NotImplementedError:
        num_threads = multiprocessing.cpu_count() or 1

    return num_threads

async def main():
    cpu_threads = get_cpu_threads()
    max_workers = int(config['Threads'].get('max_workers', fallback=cpu_threads))

    if max_workers == 0:
        # print(f"Using all available CPU threads: {cpu_threads}")
        max_workers = None  # Set to None for ThreadPoolExecutor to use all available threads
    else:
        # print(f"Number of CPU threads: {cpu_threads}")
        # print(f"Max workers for ThreadPoolExecutor: {max_workers}")
        pass

    async with aiohttp.ClientSession() as session:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            total_items = len(urls)
            total_progress = tqdm(total=total_items, desc="Total Progress", position=0)

            futures = []
            loop = asyncio.get_event_loop()

            for url in urls:
                future = loop.create_task(async_process_url(session, url, total_progress, priority_order, download_path))
                futures.append(future)

            await asyncio.gather(*futures)

            total_progress.close()

    if failed_urls:
        print("\nThe following files encountered errors during download:")
        for failed_url in failed_urls:
            print(f"- {failed_url}")

if __name__ == "__main__":
    priority_order = config.get('Download', 'priority_order', fallback='mp3, flac, m4a').split(', ')
    download_path = config.get('Download', 'download_path', fallback='')
    asyncio.run(main())
