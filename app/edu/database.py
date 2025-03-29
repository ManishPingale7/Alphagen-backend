import motor.motor_asyncio
from dotenv import load_dotenv
import os

load_dotenv()

MONGO_DETAILS = os.getenv("MONGO_URL")

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_DETAILS)

database = client.user_score_db

skill_ratings_collection = database.get_collection("user_scores")
