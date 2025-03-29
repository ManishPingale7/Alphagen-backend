from .database import skill_ratings_collection
from .schemas import SkillRatings
from fastapi.encoders import jsonable_encoder
from bson.objectid import ObjectId


async def add_skill_ratings(skill_ratings: SkillRatings) -> dict:
    skill_ratings_dict = skill_ratings.dict()
    # Insert the document into MongoDB
    result = await skill_ratings_collection.insert_one(skill_ratings_dict)
    skill_ratings_dict.pop("_id", None)
    # Build the response including the inserted ID
    response = {**skill_ratings_dict, "id": str(result.inserted_id)}
    # Use jsonable_encoder with a custom encoder for ObjectId
    return jsonable_encoder(response, custom_encoder={ObjectId: str})



async def retrieve_latest_skill_ratings() -> dict:
    latest_list = await skill_ratings_collection.find().sort("_id", -1).to_list(1)
    if latest_list:
        latest = latest_list[0]
        latest["id"] = str(latest["_id"])
        del latest["_id"]
        return latest
    else:
        return {}
