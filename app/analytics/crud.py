from .database import screenshot_collection
from .schemas import ScreenshotModel
from fastapi.encoders import jsonable_encoder
from bson.objectid import ObjectId
from datetime import datetime
from typing import List

async def add_screenshot(screenshot: ScreenshotModel) -> dict:
    """Save a screenshot to MongoDB"""
    screenshot_dict = screenshot.dict()
    
    # Set timestamp if not provided
    if not screenshot_dict.get("timestamp"):
        screenshot_dict["timestamp"] = datetime.utcnow()
    
    # Insert into database
    result = await screenshot_collection.insert_one(screenshot_dict)
    
    # Build the response
    response = {**screenshot_dict, "id": str(result.inserted_id)}
    
    # Use jsonable_encoder with a custom encoder for ObjectId
    return jsonable_encoder(response, custom_encoder={ObjectId: str})

async def retrieve_screenshots(limit: int = 10) -> List[dict]:
    """Get most recent screenshots"""
    screenshots = await screenshot_collection.find().sort("timestamp", -1).limit(limit).to_list(length=limit)
    
    # Process results
    processed_screenshots = []
    for screenshot in screenshots:
        # Convert _id to string id
        screenshot["id"] = str(screenshot["_id"])
        del screenshot["_id"]
        processed_screenshots.append(screenshot)
    
    return jsonable_encoder(processed_screenshots)

async def get_screenshot_by_id(id: str) -> dict:
    """Get a specific screenshot by ID"""
    try:
        # Convert string ID to ObjectId
        obj_id = ObjectId(id)
        screenshot = await screenshot_collection.find_one({"_id": obj_id})
        
        if screenshot:
            # Convert _id to string id
            screenshot["id"] = str(screenshot["_id"])
            del screenshot["_id"]
            return jsonable_encoder(screenshot)
        return None
    except Exception as e:
        print(f"Error retrieving screenshot by ID: {str(e)}")
        return None 