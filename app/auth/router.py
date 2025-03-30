from fastapi import APIRouter, Request, HTTPException, status, Response, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import os
import httpx
import secrets
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

router = APIRouter(prefix="/auth", tags=["Authentication"])

# OAuth configuration
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = "http://localhost:8000/auth/callback"
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

# In-memory state store for development (replace with database in production)
state_store = {}

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str]
    expires_in: int
    token_type: str
    id_token: Optional[str] = None

@router.get("/login")
async def login_google():
    """
    Generate Google OAuth2 authorization URL and return it.
    The frontend will handle the redirect.
    """
    # Generate a random state value
    state = secrets.token_urlsafe(16)
    
    # Store state in our in-memory store with a timestamp
    from datetime import datetime, timedelta
    expiry = datetime.now() + timedelta(minutes=10)
    state_store[state] = {"created": datetime.now().isoformat(), "expires": expiry.isoformat()}
    
    # Define required scopes
    scopes = [
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly"
    ]
    
    # Build the authorization URL
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "state": state,
        "prompt": "consent"
    }
    
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    auth_url = f"https://accounts.google.com/o/oauth2/auth?{query_string}"
    
    # Return both the URL and state for the frontend to handle
    return {
        "login_url": auth_url,
        "state": state
    }

@router.get("/callback")
async def auth_callback(
    request: Request, 
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None
):
    """
    Handle the OAuth2 callback from Google.
    This bypasses state validation for now.
    """
    # Debug output
    print(f"Auth Callback Received - Code: {code[:10]}..., State: {state}")
    print(f"State store contents: {state_store}")
    
    # Check for error parameter
    if error:
        return JSONResponse({
            "success": False,
            "error": error,
            "message": "Authentication failed or was cancelled by user"
        }, status_code=400)
    
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code"
        )
    
    # TEMPORARY: Skip state validation for debugging
    # In production, you must validate the state parameter
    
    token_url = "https://oauth2.googleapis.com/token"
    
    # Prepare the data required to exchange the code for tokens
    payload = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    
    try:
        async with httpx.AsyncClient() as client:
            token_response = await client.post(token_url, data=payload)
        
        if token_response.status_code != 200:
            error_text = token_response.text
            print(f"Token Error: {error_text}")
            return JSONResponse({
                "success": False,
                "error": "token_exchange_failed",
                "message": f"Failed to exchange authorization code: {error_text}"
            }, status_code=400)
        
        # Successfully got tokens
        tokens = token_response.json()
        
        # Get user info to confirm it worked
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"}
            )
            
        if user_response.status_code == 200:
            user_info = user_response.json()
            
            # For demo purposes, return everything
            # In production, you'd store tokens securely and only return necessary info
            return {
                "success": True,
                "access_token": tokens["access_token"],
                "token_type": tokens["token_type"],
                "expires_in": tokens["expires_in"],
                "user": {
                    "email": user_info.get("email"),
                    "name": user_info.get("name"),
                    "picture": user_info.get("picture")
                }
            }
        else:
            return JSONResponse({
                "success": False,
                "error": "user_info_failed",
                "message": "Could not fetch user info"
            }, status_code=400)
        
    except Exception as e:
        print(f"Exception in auth callback: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": "general_error",
            "message": str(e)
        }, status_code=500)

@router.get("/token/refresh")
async def refresh_token(refresh_token: str):
    """
    Refresh an expired access token using the refresh token.
    """
    token_url = "https://oauth2.googleapis.com/token"
    
    payload = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    
    async with httpx.AsyncClient() as client:
        token_response = await client.post(token_url, data=payload)
    
    if token_response.status_code != 200:
        raise HTTPException(
            status_code=token_response.status_code,
            detail="Failed to refresh access token"
        )
    
    # Return the new access token
    return token_response.json()

@router.get("/user/info")
async def get_user_info(access_token: str):
    """
    Get the user's profile information using the access token.
    """
    user_info_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    
    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            user_info_url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
    
    if user_response.status_code != 200:
        raise HTTPException(
            status_code=user_response.status_code,
            detail="Failed to fetch user information"
        )
    
    return user_response.json()

@router.get("/youtube-analytics")
async def get_youtube_analytics(access_token: str):
    """
    Get YouTube analytics data using an access token
    """
    try:
        # Example endpoint for channel basic stats
        url = "https://youtubeanalytics.googleapis.com/v2/reports"
        params = {
            "dimensions": "day",
            "metrics": "views,likes,subscribersGained",
            "ids": "channel==MINE",
            "startDate": "30daysAgo",
            "endDate": "today"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, 
                params=params,
                headers={"Authorization": f"Bearer {access_token}"}
            )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "success": False,
                "error_code": response.status_code,
                "error_details": response.text
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        } 