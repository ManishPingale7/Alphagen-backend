import motor.motor_asyncio
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# MongoDB connection
MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise ValueError("MONGO_URL environment variable is not set")

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)

# Database and collections
db = client.alphagen_db
screenshot_collection = db.get_collection("youtube_studio_screenshots") 