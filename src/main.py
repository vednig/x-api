from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from upstash_redis import Redis
import redis
import hashlib
import json
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from typing import Union
import os
import time
import pickle
import re
from fastapi import FastAPI
from typing import List, Dict
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import json
from fastapi.middleware.cors import CORSMiddleware


# Initialize FastAPI and Redis cache
app = FastAPI()

origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_cache = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)
redis_cache = redis
# SQLAlchemy setup for PostgreSQL

DATABASE_URL = "postgresql://<db_conn_string>"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Example model for storing data in the database
class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, index=True)
    result = Column(String)

# Create tables in the database
Base.metadata.create_all(bind=engine)

origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utility functions for Redis caching
def generate_cache_key(url: str) -> str:
    return hashlib.sha256(url.encode('utf-8')).hexdigest()

def check_cache(url: str):
    cache_key = generate_cache_key(url)
    cached_response = redis_cache.get(cache_key)
    if cached_response:
        return json.loads(cached_response)
    return None

def cache_response(url: str, data: dict):
    cache_key = generate_cache_key(url)
    redis_cache.setex(cache_key, 3600, json.dumps(data))  # Cache for 1 hour

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Check if the result exists in the database
def check_db(url: str, db):
    db_item = db.query(Item).filter(Item.url == url).first()
    return db_item

# Store result in the database
def store_in_db(url: str, result: dict, db):
    db_item = Item(url=url, result=json.dumps(result))
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

class XThreadPersistentSessionScraper:
    def __init__(self, 
                 username: str,
                 password: str,
                 headless: bool = True,
                 wait_timeout: int = 15,
                 max_scrolls: int = 2,
                 cookies_path: str = 'x_session_cookies.pkl'):
        """
        Initialize the X Thread Persistent Session Scraper
        
        :param username: X.com username or email
        :param password: X.com account password
        :param headless: Run browser in headless mode
        :param wait_timeout: Maximum wait time for page elements
        :param max_scrolls: Maximum number of scrolls to expand thread
        :param cookies_path: Path to store/load session cookies
        """
        # Credentials and paths
        self.username = username
        self.password = password
        self.cookies_path = cookies_path
        
        # Chrome options setup
        self.chrome_options = Options()
        if headless:
            self.chrome_options.add_argument("--headless")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        
        # Enable logging to capture network traffic
        self.chrome_options.add_argument("--enable-logging")
        self.chrome_options.add_argument("--v=1")  # Set verbosity level to capture network logs
        self.chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})



        
        # User-Agent to mimic browser
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        
        # Configuration
        self.wait_timeout = wait_timeout
        self.max_scrolls = max_scrolls
        
        # Initialize driver and wait
        self.driver = None
        self.wait = None
        
        # Initialize session
        self._initialize_session()
    
    def _initialize_session(self):
        """
        Initialize browser session with persistent login
        """
        # Create new webdriver
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.wait = WebDriverWait(self.driver, self.wait_timeout)


        # Initialize list to store video URLs
        self.video_urls = []
        # def response_intercepter(request):
        #     print(f"Network request: {request.url}")
        # # Capture network requests that are of interest
        # self.driver.request_interceptor = response_intercepter

        # Try to load existing cookies
        if os.path.exists(self.cookies_path):
            try:
                self._load_cookies()
                return
            except Exception as e:
                print(f"Failed to load existing cookies: {e}")
        
        # If no valid cookies, perform fresh login
        self._perform_fresh_login()



    def _capture_network_requests(self, params):
        """
        Capture network requests and filter for .m3u8 video URLs
        
        :param params: Network request parameters from DevTools Protocol
        """
        url = params.get("request", {}).get("url", "")
        # print(f"Network request: {url}")
        if ".m3u8" in url:
            # Extract tweet ID from the URL (or other mechanisms as required)
            tweet_id = self._extract_tweet_id_from_url(url)
            if tweet_id:
                self.video_urls.append({"tweet_id": tweet_id, "video_url": url})

    def _extract_tweet_id_from_url(self, url: str) -> str:
        """
        Extract the tweet ID from the URL pattern (can vary depending on the site structure)
        
        :param url: The network URL (likely containing the tweet ID)
        :return: The tweet ID if possible, or None
        """
        # Extract tweet ID from the URL (example pattern)
        match = re.search(r"ext_tw_video/(\d+)/", url)
        if match:
            return match.group(1)
        return None

    def _perform_fresh_login(self):
        """
        Perform a fresh login and save cookies
        """
        try:
            # Navigate to login page
            self.driver.get("https://x.com/login")
            
            # Wait for username input
            username_input = self.wait.until(
                EC.presence_of_element_located((By.NAME, "text"))
            )
            username_input.send_keys(self.username)
            
            # Click Next button
            next_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Next')]"))
            )
            next_button.click()
            
            # Wait for password input
            password_input = self.wait.until(
                EC.presence_of_element_located((By.NAME, "password"))
            )
            password_input.send_keys(self.password)
            
            # Click Login button
            login_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Log in')]"))
            )
            login_button.click()
            
            # Wait for login to complete
            self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//nav"))
            )
            
            # Save cookies after successful login
            self._save_cookies()
            
            # print("Successfully logged in and saved session.")
        
        except Exception as e:
            raise RuntimeError(f"Login failed: {e}")
    
    def _save_cookies(self):
        """
        Save browser cookies to a file
        """
        with open(self.cookies_path, 'wb') as filehandler:
            pickle.dump(self.driver.get_cookies(), filehandler)
    
    def _load_cookies(self):
        """
        Load cookies and add to browser
        """
        # Navigate to X.com first to set domain
        self.driver.get("https://x.com")
        
        # Load cookies
        with open(self.cookies_path, 'rb') as cookiesfile:
            cookies = pickle.load(cookiesfile)
            
        # Add each cookie to the browser
        for cookie in cookies:
            try:
                self.driver.add_cookie(cookie)
            except Exception as e:
                print(f"Error adding cookie: {e}")
        
        # Refresh to apply cookies
        self.driver.refresh()
        
        # Validate session
        self._validate_session()
    
    def _validate_session(self):
        """
        Validate if the loaded session is still active
        """
        try:
            # Navigate to home page
            self.driver.get("https://x.com/home")
            
            # Check for elements that indicate an active session
            self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//nav"))
            )
        except Exception:
            # If validation fails, perform fresh login
            # print("Existing session invalid. Performing fresh login.")
            self.driver.quit()
            self._initialize_session()
    
    def scrape_comprehensive_thread(self, thread_url: str) -> List[Dict[str, str]]:
        """
        Comprehensively scrape a logged-in X thread
        
        :param thread_url: Public URL of the thread
        :return: List of tweets in the thread
        """
        try:
            # Navigate to thread
            self.driver.get(thread_url)
            
            # Wait for initial tweets to load
            self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//article"))
            )
            # Scroll was here
            self.complete_thread = False

            # Extract thread tweets
            tweets = self._extract_comprehensive_tweets(thread_url)
            
            # Scroll to expand thread
            self._scroll_thread()
            
            return tweets
        
        except Exception as e:
            raise RuntimeError(f"Failed to scrape thread: {e}")
    def _scroll_fast(self):
        """
        Scroll the page to load entire thread but not videos
        """
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        self.scroll_count = 0
        # Scroll to bottom
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        
        # Wait for potential new content
        time.sleep(1)
        
        # Calculate new scroll height
        new_height = self.driver.execute_script("return document.body.scrollHeight")
        
        # Break if no new content
        if new_height == last_height:
            self.complete_thread = True
            return
        
        last_height = new_height
        self.scroll_count += 1
        


    def _scroll_thread(self):
        """
        Scroll the page to load entire thread
        """
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        scroll_count = 0
        
        while scroll_count < self.max_scrolls:
            # Scroll to bottom
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            
            # Wait for potential new content
            time.sleep(4)
            
            # Calculate new scroll height
            new_height = self.driver.execute_script("return document.body.scrollHeight/2")
            
            # Break if no new content
            if new_height == last_height:
                break
            
            last_height = new_height
            scroll_count += 1
    
    def _extract_comprehensive_tweets(self, original_url: str) -> List[Dict[str, str]]:
        """
        Extract comprehensive tweet information from the thread
        
        :param original_url: Original thread URL to extract first tweet details
        :return: List of tweet dictionaries
        """
        # Extract first tweet details
        first_tweet = self._extract_first_tweet(original_url)

        # Find all tweets matching the original author and similar timestamp
        tweets = []
        while not self.complete_thread:
            tweet_elements = self.driver.find_elements(By.XPATH, "//article")
            # print(f"Found Total {len(tweet_elements)} tweets in thread.")
            for element in tweet_elements:
                try:
                    # Extract author details
                    author_elements = element.find_elements(
                        By.XPATH, ".//div[@data-testid='User-Name']//span//span"
                    )
                    author = author_elements[0].text if author_elements else "Unknown author"
                    if (first_tweet['author'].lower() in author.lower() or 
                            author.lower() in first_tweet['author'].lower()):
                        # print(f"Author: {author}")
                                
                        # Extract timestamp
                        timestamp_elements = element.find_elements(By.XPATH, ".//time")
                        timestamp = timestamp_elements[0].get_attribute('datetime') if timestamp_elements else "No timestamp"
                        
                        # Extract tweet text
                        tweet_text_elements = element.find_elements(
                            By.XPATH, ".//div[@data-testid='tweetText']"
                        )
                        if tweet_text_elements.__len__() > 1:
                            tweet_text = ""
                            for i in range(len(tweet_text_elements)):
                                # for span in tweet_text_elements[i].find_elements(By.TAG_NAME, 'span'):
                                tweet_text += tweet_text_elements[i].text
                                # # Add space or image
                                # for img in tweet_elements[i].find_elements(By.TAG_NAME, 'img'):
                                #     print(f"Image: {img.get_attribute('src')}")
                                #     # for img in tweet_elements[i].find_elements(By.TAG_NAME, 'img'):
                                #     #     tweet_text += "[~~~img~~~]"
                                #     #     print(f"Image: {img.get_attribute('src')}")
                                
                        else:
                            tweet_text = tweet_text_elements[0].text if tweet_text_elements else "No text found"
                        # print((original_url.split("/")[-3]+"/"+original_url.split("/")[-2]))
                        # Extract tweet ID
                        tweet_id_elements = element.find_elements(
                            By.XPATH, ".//a[contains(@href, '/{semipath_url}')]".format(semipath_url=original_url.split("/")[-3]+"/"+original_url.split("/")[-2])
                        )

                        tweet_id = self._extract_tweet_id(tweet_id_elements)
                        # print(f"Tweet ID: {tweet_id}")
                        # Extract media (images, GIFs, videos, links) for this tweet
                        media_urls = self._extract_media_for_tweet(element,tweet_id)

                        tweet_links = element.find_elements(By.XPATH, ".//a[contains(@href, 'https://t.co/')]")
                        links = []
                        for link in tweet_links:
                            # print(f"Link: {link.get_attribute('href')}")
                            if link.get_attribute('href') not in links:
                                links.append(link.get_attribute('href'))
                        
                        # Check if tweet matches original author and is part of the thread
                        if (self._is_matching_thread_tweet(first_tweet, author, timestamp)):
                            tweets.append({
                                "author": author,
                                "text": tweet_text,
                                "tweet_id": tweet_id,
                                "timestamp": timestamp,
                                "media": media_urls,  # Store media for this tweet
                                "links": links  # Store links for this tweet
                            })
                    else:
                        continue
                
                except Exception as e:
                    print(f"Error extracting tweet: {e}")
                    continue
            self._scroll_fast()
        return tweets
    
    def _extract_first_tweet(self, thread_url: str) -> Dict[str, str]:
        """
        Extract details of the first tweet in the thread
        
        :param thread_url: URL of the thread
        :return: Dictionary with first tweet details
        """
        try:
            # Find first tweet elements
            author_elements = self.driver.find_elements(
                By.XPATH, "//div[@data-testid='User-Name']//span//span"
            )
            # print(f"Author: {author_elements[0].text}")
            timestamp_elements = self.driver.find_elements(
                By.XPATH, "(//article//time)[1]"
            )
            # print(f"Timestamp: {timestamp_elements[0].get_attribute('datetime')}")
            first_tweet = {
                "author": author_elements[0].text if author_elements else "Unknown author",
                "timestamp": timestamp_elements[0].get_attribute('datetime') if timestamp_elements else "No timestamp"
            }
            # print(f"First tweet: {first_tweet}")
            return first_tweet
        
        except Exception as e:
            # print(f"Error extracting first tweet: {e}")
            return {"author": "Unknown", "timestamp": "No timestamp"}
        
    def _extract_tweet_id(self, tweet_element) -> str:
        """
        Extract tweet ID from the tweet element
        
        :param tweet_element: Tweet HTML element
        :return: Tweet ID
        """
        tweet_id = ""
        try:
            tweet_id = tweet_element[0].get_attribute('href').split("/")[-1]
            # print(f"Tweet ID: {tweet_id}")
        except Exception:
            pass
        return tweet_id

    def _extract_media_for_tweet(self, tweet_element,tweet_id:str) -> List[str]:
        """
        Extract media URLs for a specific tweet
        
        :param tweet_element: The tweet element containing media
        :return: List of media URLs (images, videos, etc.)
        """
        media_urls = []
         
        # Extract images
        images = tweet_element.find_elements(By.TAG_NAME, 'img')
        for img in images:
            src = img.get_attribute('src')
            if src:
                media_urls.append(src)
        
        # # Extract videos with m3u8 links
        # videos = tweet_element.find_elements(By.TAG_NAME, 'video')
        # for video in videos:
        #     src = video.get_attribute('src')
        #     if src and src.startswith("blob:"):
        #         self.driver.execute_script("arguments.play();", video)
        #     else:
        #         # Check for <source> tags inside <video> tag
        #         sources = video.find_elements(By.TAG_NAME, 'source')
        #         for source in sources:
        #             src = source.get_attribute('src')
        #             if src and src.startswith("blob:"):
        #                 self.driver.execute_script("arguments.play();", source)
         
        # Add the m3u8 video URL if available for this tweet
        # print(f"Video URLs: {self.video_urls}")
        # if tweet_id in self.video_urls:
        #     media_urls.append(self.video_urls[tweet_id])
        
        return media_urls
    
    def _is_matching_thread_tweet(self, first_tweet: Dict[str, str], author: str, timestamp: str) -> bool:
        """
        Determine if a tweet is part of the original thread
        
        :param first_tweet: Details of the first tweet
        :param author: Author of the current tweet
        :param timestamp: Timestamp of the current tweet
        :return: Boolean indicating if tweet is part of the thread
        """
        # Check author similarity (allowing for slight variations)
        author_match = (first_tweet['author'].lower() in author.lower() or 
                        author.lower() in first_tweet['author'].lower())
        
        # Extract date from timestamp for loose matching
        def extract_date(ts: str) -> str:
            match = re.search(r'\d{4}-\d{2}-\d{2}', ts)
            return match.group(0) if match else ts
        
        date_match = (extract_date(first_tweet['timestamp']) == extract_date(timestamp))
        # print(f"Author: {author}, Timestamp: {timestamp}, Author match: {author_match}, Date match: {date_match}")
        return author_match and date_match
    
    def close(self):
        """
        Close the browser
        """
        
        # Gets all the logs from performance in Chrome 
        logs = self.driver.get_log("performance") 
    
        # Opens a writable JSON file and writes the logs in it 
        with open("network_log.json", "w", encoding="utf-8") as f: 
            f.write("[") 
    
            # Iterates every logs and parses it using JSON 
            for log in logs: 
                network_log = json.loads(log["message"])["message"] 
    
                # Checks if the current 'method' key has any 
                # Network related value. 
                if("Network.response" in network_log["method"] 
                        or "Network.request" in network_log["method"] 
                        or "Network.webSocket" in network_log["method"]): 
    
                    # Writes the network log to a JSON file by 
                    # converting the dictionary to a JSON string 
                    # using json.dumps(). 
                    f.write(json.dumps(network_log)+",") 
            f.write("{}]") 

        # Save cookies before closing
        self._save_cookies()
        self.driver.quit()

# Example usage
async def main(url: str):
    # Credentials (consider using environment variables)
    USERNAME = os.getenv('X_USERNAME', '<access_username>')
    PASSWORD = os.getenv('X_PASSWORD', '<password>')
    thread = []
    complete_thread =""
    # URL of the public thread
    THREAD_URL = url
    
    # Create scraper with persistent session
    scraper = XThreadPersistentSessionScraper(
        username=USERNAME, 
        password=PASSWORD
    )
    
    try:
        # Scrape thread
        thread = scraper.scrape_comprehensive_thread(THREAD_URL)
        
        # Print unrolled thread
        print(f"Thread from {thread[0]['author']}:")
        print("-" * 50)
        complete_thread = [tweet['text'] for tweet in thread]
        for i, tweet in enumerate(thread, 1):
            continue
            # print(f"Tweet {i}:")
            # print(f"Text: {tweet['text']}\n")
            # print(f"ID: {tweet['tweet_id']}\n")
            # print(f"Media: {tweet['media']}\n")
            # print(f"Links: {tweet['links']}\n")
        # print(f"Thread: {complete_thread}")
        # print("\n".join(complete_thread))
    except Exception as e:
        print(f"Scraping failed: {e}")
    
    finally:
        # Close and save session
        scraper.close()
    
    print("Including M3U8 in tweets")
    # Including M3U8 in tweets
       # Read the JSON File and parse it using 
    # json.loads() to find the urls containing images. 
    json_file_path = "network_log.json"
    with open(json_file_path, "r", encoding="utf-8") as f: 
        logs = json.loads(f.read()) 
    video_urls = []
    # Iterate the logs 
    for log in logs: 
  
        # Except block will be accessed if any of the 
        # following keys are missing. 
        try: 
            # URL is present inside the following keys 
            url = log["params"]["request"]["url"] 
  
            # Checks if the extension is .png or .jpg 
            if ".m3u8" in url:
                print(url, end='\n\n') 
                if url not in video_urls:
                    video_urls.append(url)
        except Exception as e: 
            pass
    print(f"Video URLs: {video_urls}")
    response = []
    

    for i,tweet in enumerate(thread, 1):
        # print(i)
        thumbnailurl_list = [i for i in tweet['media'] if 'ext_tw_video_thumb' in i]                
        # print(f"Tweet Media: { thumbnailurl_list}:")
        if thumbnailurl_list:
                                    
            # Regular expressions to extract IDs
            thumbnail_pattern = r"/ext_tw_video_thumb/(\d+)/"
            video_pattern = r"/ext_tw_video/(\d+)/"

            # Extract IDs from thumbnail URLs
            thumbnail_id = [re.search(thumbnail_pattern, url).group(1) for url in thumbnailurl_list if re.search(thumbnail_pattern, url)]
            video_list = []
            def new_video(url):
                video_list.append(url)
                return video_list

            # Extract IDs from video URLs
            video_id_map = {re.search(video_pattern, url).group(1): new_video(url)  for url in video_urls if re.search(video_pattern, url)}
            print(f"Thumbnail ID Map: {thumbnail_id}")
            print(f"Video ID Map: {video_id_map}")
            for link in video_id_map.get(thumbnail_id[0]):
                tweet["media"].append(link)
            # tweet["media"].append(video_id_map.get(thumbnail_id[0]))
            # for thumbnail_id, thumbnail_url in thumbnail_id_map.items():
            #     if thumbnail_id in video_id_map:
            #         tweet['media'].append(video_id_map[thumbnail_id])
            # 
            # # Regular expressions to extract IDs
            # thumbnail_pattern = r"/ext_tw_video_thumb/(\d+)/"
            # video_pattern = r"/ext_tw_video/(\d+)/"
            # # Extracting IDs
            # thumbnail_id = re.search(thumbnail_pattern, tweet['media'][-1]).group(1)
            # video_id = re.search(video_pattern, video_urls[i]).group(1)
            # print(f"Thumbnail ID: {thumbnail_id}, Video ID: {video_id}")
            # if thumbnail_id == video_id:
            #     tweet['media'].append(video_urls[i])
            
        response.append(tweet)
    return response
# Database initialization logic
def init_db():
    # Check if the database tables exist, if not, create them
    Base.metadata.create_all(bind=engine)

# Redis initialization logic
def init_redis():
    # Ensure Redis is reachable (ping the Redis server)
    try:
        redis_cache.ping()  # Ping Redis server to check if it's available
        print("Redis is connected and ready.")
    except redis.ConnectionError:
        print("Failed to connect to Redis. Make sure Redis is running.")

# FastAPI Event to initialize both DB and Redis on first run
@app.on_event("startup")
def on_startup():
    # Initialize database (create tables if not exist)
    init_db()

    # Initialize Redis (check connectivity)
    init_redis()

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/x-thread-api")
async def read_item(url: str, db = Depends(get_db)):
    # Step 1: Check cache first
    cached_data = check_cache(url)
    if cached_data:
        return cached_data
    
    # Step 2: Check database if not in cache
    db_item = check_db(url, db)
    if db_item:
        result = json.loads(db_item.result)
        # Cache the result from DB
        cache_response(url, result)
        return result
    
    # Step 3: Compute if not found in cache or DB
    result = await main(url)
    
    # Step 4: Store the result in the database
    store_in_db(url, result, db)
    
    # Step 5: Cache the result for future use
    cache_response(url, result)
    
    return result
