from fastapi import APIRouter, HTTPException, Query
import httpx
from typing import Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

router = APIRouter(prefix="/youtube", tags=["YouTube Analytics"])

class DashboardResponse(BaseModel):
    success: bool
    channel_info: dict
    performance: dict
    audience: dict
    traffic_sources: dict
    content_performance: dict
    revenue: Optional[dict] = None
    error: Optional[str] = None

@router.get("/dashboard")
async def get_dashboard(
    access_token: str,
    days: int = Query(30, ge=1, le=90, description="Number of days to analyze"),
    include_geography: bool = Query(True, description="Include geographic data"),
    include_demographics: bool = Query(True, description="Include demographic data"),
    include_device_data: bool = Query(True, description="Include device and platform data"),
    comparison_period: bool = Query(True, description="Include comparison with previous period")
):
    """
    Generate a comprehensive YouTube Studio dashboard with detailed metrics
    """
    try:
        # Calculate date ranges
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # For comparison period
        prev_end_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        prev_start_date = (datetime.now() - timedelta(days=days*2)).strftime("%Y-%m-%d")
        
        # Headers for all requests
        headers = {"Authorization": f"Bearer {access_token}"}
        dashboard_data = {"success": True}
        
        async with httpx.AsyncClient() as client:
            # ==== CHANNEL OVERVIEW ====
            channel_response = await client.get(
                "https://youtube.googleapis.com/youtube/v3/channels",
                params={
                    "part": "snippet,statistics,brandingSettings,contentDetails,status,topicDetails",
                    "mine": "true"
                },
                headers=headers
            )
            
            if channel_response.status_code != 200:
                return {"success": False, "error": f"Channel info error: {channel_response.text}"}
            
            channel_data = channel_response.json()
            if "items" not in channel_data or len(channel_data["items"]) == 0:
                return {"success": False, "error": "No channel found"}
            
            channel = channel_data["items"][0]
            dashboard_data["channel"] = {
                "id": channel["id"],
                "title": channel["snippet"]["title"],
                "description": channel["snippet"]["description"],
                "customUrl": channel["snippet"].get("customUrl"),
                "country": channel["snippet"].get("country"),
                "publishedAt": channel["snippet"]["publishedAt"],
                "thumbnails": channel["snippet"]["thumbnails"],
                "banner": channel.get("brandingSettings", {}).get("image", {}).get("bannerExternalUrl"),
                "keywords": channel.get("brandingSettings", {}).get("channel", {}).get("keywords"),
                "stats": {
                    "viewCount": int(channel["statistics"].get("viewCount", 0)),
                    "subscriberCount": int(channel["statistics"].get("subscriberCount", 0)),
                    "videoCount": int(channel["statistics"].get("videoCount", 0)),
                    "commentCount": int(channel["statistics"].get("commentCount", 0))
                },
                "topics": channel.get("topicDetails", {}).get("topicCategories", []),
                "status": {
                    "privacyStatus": channel["status"].get("privacyStatus"),
                    "isLinked": channel["status"].get("isLinked"),
                    "longUploadsStatus": channel["status"].get("longUploadsStatus"),
                    "madeForKids": channel["status"].get("madeForKids")
                }
            }
            
            # ==== SUMMARY ANALYTICS ====
            try:
                summary_response = await client.get(
                    "https://youtubeanalytics.googleapis.com/v2/reports",
                    params={
                        "ids": "channel==MINE",
                        "startDate": start_date,
                        "endDate": end_date,
                        "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost,likes,dislikes,shares,comments,annotationImpressions,annotationClickableImpressions,annotationClicks,annotationClickThroughRate,cardImpressions,cardClicks,cardClickRate,annotationCloseRate"
                    },
                    headers=headers
                )
                
                if summary_response.status_code == 200:
                    dashboard_data["summary"] = summary_response.json()
                    
                    # Add comparison with previous period
                    if comparison_period:
                        prev_summary_response = await client.get(
                            "https://youtubeanalytics.googleapis.com/v2/reports",
                            params={
                                "ids": "channel==MINE",
                                "startDate": prev_start_date,
                                "endDate": prev_end_date,
                                "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost,likes,dislikes,shares,comments"
                            },
                            headers=headers
                        )
                        
                        if prev_summary_response.status_code == 200:
                            prev_data = prev_summary_response.json()
                            current_metrics = dashboard_data["summary"].get("rows", [[0] * len(dashboard_data["summary"].get("columnHeaders", []))])[0]
                            prev_metrics = prev_data.get("rows", [[0] * len(prev_data.get("columnHeaders", []))])[0]
                            
                            # Calculate percentage changes
                            changes = {}
                            for i, header in enumerate(dashboard_data["summary"].get("columnHeaders", [])):
                                name = header.get("name")
                                if i < len(prev_metrics) and prev_metrics[i] > 0:
                                    pct_change = ((current_metrics[i] - prev_metrics[i]) / prev_metrics[i]) * 100
                                    changes[name] = {
                                        "current": current_metrics[i],
                                        "previous": prev_metrics[i],
                                        "change": current_metrics[i] - prev_metrics[i],
                                        "pct_change": round(pct_change, 2)
                                    }
                                else:
                                    changes[name] = {
                                        "current": current_metrics[i],
                                        "previous": 0,
                                        "change": current_metrics[i],
                                        "pct_change": 100 if current_metrics[i] > 0 else 0
                                    }
                            
                            dashboard_data["comparison"] = changes
                else:
                    dashboard_data["summary"] = {"error": summary_response.text}
            except Exception as e:
                dashboard_data["summary"] = {"error": str(e)}
            
            # ==== DAILY PERFORMANCE ====
            try:
                daily_response = await client.get(
                    "https://youtubeanalytics.googleapis.com/v2/reports",
                    params={
                        "ids": "channel==MINE",
                        "startDate": start_date,
                        "endDate": end_date,
                        "dimensions": "day",
                        "metrics": "views,estimatedMinutesWatched,averageViewDuration,likes,subscribersGained,subscribersLost,shares,comments",
                        "sort": "day"
                    },
                    headers=headers
                )
                
                if daily_response.status_code == 200:
                    daily_data = daily_response.json()
                    
                    # Format into a more frontend-friendly structure
                    if "rows" in daily_data and len(daily_data["rows"]) > 0:
                        formatted_daily = {
                            "dates": [],
                            "metrics": {}
                        }
                        
                        # Initialize metrics arrays
                        for header in daily_data["columnHeaders"][1:]:  # Skip date column
                            formatted_daily["metrics"][header["name"]] = []
                        
                        # Fill in data
                        for row in daily_data["rows"]:
                            formatted_daily["dates"].append(row[0])
                            for i, value in enumerate(row[1:]):
                                header_name = daily_data["columnHeaders"][i+1]["name"]
                                formatted_daily["metrics"][header_name].append(value)
                        
                        dashboard_data["daily_performance"] = formatted_daily
                    else:
                        dashboard_data["daily_performance"] = daily_data
                else:
                    dashboard_data["daily_performance"] = {"error": daily_response.text}
            except Exception as e:
                dashboard_data["daily_performance"] = {"error": str(e)}
            
            # ==== TRAFFIC SOURCES ====
            try:
                traffic_response = await client.get(
                    "https://youtubeanalytics.googleapis.com/v2/reports",
                    params={
                        "ids": "channel==MINE",
                        "startDate": start_date,
                        "endDate": end_date,
                        "dimensions": "insightTrafficSourceType",
                        "metrics": "views,estimatedMinutesWatched,averageViewDuration",
                        "sort": "-views"
                    },
                    headers=headers
                )
                
                if traffic_response.status_code == 200:
                    traffic_data = traffic_response.json()
                    
                    # Format into a more dashboard-friendly structure
                    if "rows" in traffic_data and len(traffic_data["rows"]) > 0:
                        traffic_sources = []
                        total_views = sum(row[1] for row in traffic_data["rows"])
                        
                        for row in traffic_data["rows"]:
                            percentage = (row[1] / total_views) * 100 if total_views > 0 else 0
                            traffic_sources.append({
                                "source": row[0],
                                "views": row[1],
                                "watchTime": row[2],
                                "avgViewDuration": row[3],
                                "percentage": round(percentage, 2)
                            })
                        
                        dashboard_data["traffic_sources"] = traffic_sources
                    else:
                        dashboard_data["traffic_sources"] = traffic_data
                else:
                    dashboard_data["traffic_sources"] = {"error": traffic_response.text}
            except Exception as e:
                dashboard_data["traffic_sources"] = {"error": str(e)}
            
            # ==== TOP VIDEOS ====
            try:
                videos_response = await client.get(
                    "https://youtubeanalytics.googleapis.com/v2/reports",
                    params={
                        "ids": "channel==MINE",
                        "startDate": start_date,
                        "endDate": end_date,
                        "dimensions": "video",
                        "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,likes,comments",
                        "sort": "-views",
                        "maxResults": 10
                    },
                    headers=headers
                )
                
                if videos_response.status_code == 200:
                    videos_data = videos_response.json()
                    
                    # Get video details to enhance the analytics data
                    video_ids = []
                    if "rows" in videos_data and len(videos_data["rows"]) > 0:
                        video_ids = [row[0] for row in videos_data["rows"]]
                    
                    if video_ids:
                        video_details_response = await client.get(
                            "https://youtube.googleapis.com/youtube/v3/videos",
                            params={
                                "part": "snippet,contentDetails,statistics",
                                "id": ",".join(video_ids)
                            },
                            headers=headers
                        )
                        
                        if video_details_response.status_code == 200:
                            video_details = {item["id"]: item for item in video_details_response.json().get("items", [])}
                            
                            # Merge analytics and video details
                            top_videos = []
                            for row in videos_data.get("rows", []):
                                video_id = row[0]
                                details = video_details.get(video_id, {})
                                
                                video_data = {
                                    "id": video_id,
                                    "title": details.get("snippet", {}).get("title", "Unknown"),
                                    "publishedAt": details.get("snippet", {}).get("publishedAt"),
                                    "thumbnail": details.get("snippet", {}).get("thumbnails", {}).get("medium", {}).get("url"),
                                    "duration": details.get("contentDetails", {}).get("duration"),
                                    "metrics": {}
                                }
                                
                                # Add metrics from analytics
                                for i, header in enumerate(videos_data.get("columnHeaders", [])[1:], 1):  # Skip video ID
                                    video_data["metrics"][header.get("name")] = row[i]
                                
                                top_videos.append(video_data)
                                
                            dashboard_data["top_videos"] = top_videos
                        else:
                            dashboard_data["top_videos"] = {"error": video_details_response.text}
                    else:
                        dashboard_data["top_videos"] = videos_data
                else:
                    dashboard_data["top_videos"] = {"error": videos_response.text}
            except Exception as e:
                dashboard_data["top_videos"] = {"error": str(e)}
            
            # ==== AUDIENCE DEMOGRAPHICS (if requested) ====
            if include_demographics:
                try:
                    demographics_response = await client.get(
                        "https://youtubeanalytics.googleapis.com/v2/reports",
                        params={
                            "ids": "channel==MINE",
                            "startDate": start_date,
                            "endDate": end_date,
                            "dimensions": "ageGroup,gender",
                            "metrics": "viewerPercentage",
                            "sort": "-viewerPercentage"
                        },
                        headers=headers
                    )
                    
                    if demographics_response.status_code == 200:
                        dashboard_data["demographics"] = demographics_response.json()
                    else:
                        dashboard_data["demographics"] = {"error": demographics_response.text}
                except Exception as e:
                    dashboard_data["demographics"] = {"error": str(e)}
            
            # ==== GEOGRAPHIC DATA (if requested) ====
            if include_geography:
                try:
                    geography_response = await client.get(
                        "https://youtubeanalytics.googleapis.com/v2/reports",
                        params={
                            "ids": "channel==MINE",
                            "startDate": start_date,
                            "endDate": end_date,
                            "dimensions": "country",
                            "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained",
                            "sort": "-views",
                            "maxResults": 25
                        },
                        headers=headers
                    )
                    
                    if geography_response.status_code == 200:
                        dashboard_data["geography"] = geography_response.json()
                    else:
                        dashboard_data["geography"] = {"error": geography_response.text}
                except Exception as e:
                    dashboard_data["geography"] = {"error": str(e)}
            
            # ==== DEVICE AND PLATFORM DATA (if requested) ====
            if include_device_data:
                try:
                    device_response = await client.get(
                        "https://youtubeanalytics.googleapis.com/v2/reports",
                        params={
                            "ids": "channel==MINE",
                            "startDate": start_date,
                            "endDate": end_date,
                            "dimensions": "deviceType,operatingSystem",
                            "metrics": "views,estimatedMinutesWatched,averageViewDuration",
                            "sort": "-views"
                        },
                        headers=headers
                    )
                    
                    if device_response.status_code == 200:
                        dashboard_data["devices"] = device_response.json()
                    else:
                        dashboard_data["devices"] = {"error": device_response.text}
                except Exception as e:
                    dashboard_data["devices"] = {"error": str(e)}
            
            # ==== WATCH TIME BY TIME OF DAY ====
            try:
                time_of_day_response = await client.get(
                    "https://youtubeanalytics.googleapis.com/v2/reports",
                    params={
                        "ids": "channel==MINE",
                        "startDate": start_date,
                        "endDate": end_date,
                        "dimensions": "day,hour",
                        "metrics": "views,estimatedMinutesWatched",
                        "sort": "day,hour"
                    },
                    headers=headers
                )
                
                if time_of_day_response.status_code == 200:
                    time_data = time_of_day_response.json()
                    
                    # Process into heatmap-friendly format
                    if "rows" in time_data and len(time_data["rows"]) > 0:
                        hours = range(24)
                        days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                        
                        # Initialize heatmap data
                        heatmap = {
                            "hourly_views": [0] * 24,  # Sum by hour of day
                            "hourly_watch_time": [0] * 24,  # Sum by hour of day
                            "day_hour_views": [[0 for _ in range(24)] for _ in range(7)],  # 7 days x 24 hours
                            "day_hour_watch_time": [[0 for _ in range(24)] for _ in range(7)]  # 7 days x 24 hours
                        }
                        
                        # Fill in the data
                        for row in time_data["rows"]:
                            date_str = row[0]  # Format: YYYY-MM-DD
                            hour = int(row[1])
                            views = row[2]
                            watch_time = row[3]
                            
                            # Get day of week (0 = Monday, 6 = Sunday)
                            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                            day_of_week = date_obj.weekday()
                            
                            # Add to hourly totals
                            heatmap["hourly_views"][hour] += views
                            heatmap["hourly_watch_time"][hour] += watch_time
                            
                            # Add to day/hour matrix
                            heatmap["day_hour_views"][day_of_week][hour] += views
                            heatmap["day_hour_watch_time"][day_of_week][hour] += watch_time
                        
                        dashboard_data["time_of_day"] = {
                            "raw_data": time_data,
                            "heatmap": heatmap,
                            "hours": list(hours),
                            "days_of_week": days_of_week
                        }
                    else:
                        dashboard_data["time_of_day"] = time_data
                else:
                    dashboard_data["time_of_day"] = {"error": time_of_day_response.text}
            except Exception as e:
                dashboard_data["time_of_day"] = {"error": str(e)}
            
            # ==== PLAYLISTS ====
            try:
                playlists_response = await client.get(
                    "https://youtube.googleapis.com/youtube/v3/playlists",
                    params={
                        "part": "snippet,contentDetails,status",
                        "mine": "true",
                        "maxResults": 50
                    },
                    headers=headers
                )
                
                if playlists_response.status_code == 200:
                    dashboard_data["playlists"] = playlists_response.json()
                else:
                    dashboard_data["playlists"] = {"error": playlists_response.text}
            except Exception as e:
                dashboard_data["playlists"] = {"error": str(e)}
            
            # ==== SUBSCRIBER SOURCES ====
            try:
                sub_sources_response = await client.get(
                    "https://youtubeanalytics.googleapis.com/v2/reports",
                    params={
                        "ids": "channel==MINE",
                        "startDate": start_date,
                        "endDate": end_date,
                        "dimensions": "subscribedStatus",
                        "metrics": "views,estimatedMinutesWatched,subscribersGained,subscribersLost",
                        "sort": "-views"
                    },
                    headers=headers
                )
                
                if sub_sources_response.status_code == 200:
                    dashboard_data["subscriber_behavior"] = sub_sources_response.json()
                else:
                    dashboard_data["subscriber_behavior"] = {"error": sub_sources_response.text}
            except Exception as e:
                dashboard_data["subscriber_behavior"] = {"error": str(e)}
                
            # ==== KEYWORD PERFORMANCE ====
            try:
                keyword_response = await client.get(
                    "https://youtubeanalytics.googleapis.com/v2/reports",
                    params={
                        "ids": "channel==MINE",
                        "startDate": start_date,
                        "endDate": end_date,
                        "dimensions": "insightSearchTerm",
                        "metrics": "views",
                        "sort": "-views",
                        "maxResults": 20
                    },
                    headers=headers
                )
                
                if keyword_response.status_code == 200:
                    dashboard_data["search_keywords"] = keyword_response.json()
                else:
                    dashboard_data["search_keywords"] = {"error": keyword_response.text}
            except Exception as e:
                dashboard_data["search_keywords"] = {"error": str(e)}
            
            return dashboard_data
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Error generating dashboard: {str(e)}"
        }

# Additional endpoints for specific data

@router.get("/videos")
async def get_videos(
    access_token: str,
    max_results: int = Query(50, ge=1, le=50)
):
    """Get a list of videos on the channel"""
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://youtube.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "forMine": "true",
                    "type": "video",
                    "maxResults": max_results
                },
                headers=headers
            )
            
            if response.status_code != 200:
                return {"success": False, "error": response.text}
            
            return {"success": True, "videos": response.json()}
    
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.get("/video-analytics/{video_id}")
async def get_video_analytics(
    video_id: str,
    access_token: str,
    days: int = Query(30, ge=1, le=90)
):
    """Get detailed analytics for a specific video"""
    try:
        # Calculate date range
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            # Get video details
            video_response = await client.get(
                "https://youtube.googleapis.com/youtube/v3/videos",
                params={"part": "snippet,statistics,contentDetails", "id": video_id},
                headers=headers
            )
            
            # Get video analytics
            analytics_response = await client.get(
                "https://youtubeanalytics.googleapis.com/v2/reports",
                params={
                    "dimensions": "day",
                    "metrics": "views,estimatedMinutesWatched,averageViewDuration,likes,subscribersGained",
                    "ids": f"video=={video_id}",
                    "startDate": start_date,
                    "endDate": end_date
                },
                headers=headers
            )
            
            # Get audience retention if available
            retention_response = None
            try:
                retention_response = await client.get(
                    "https://youtubeanalytics.googleapis.com/v2/reports",
                    params={
                        "dimensions": "elapsedVideoTimeRatio",
                        "metrics": "audienceWatchRatio,relativeRetentionPerformance",
                        "ids": f"video=={video_id}",
                        "startDate": start_date,
                        "endDate": end_date
                    },
                    headers=headers
                )
            except Exception:
                # Retention data might not be available
                pass
            
            return {
                "success": True,
                "video_details": video_response.json() if video_response.status_code == 200 else {"error": video_response.text},
                "analytics": analytics_response.json() if analytics_response.status_code == 200 else {"error": analytics_response.text},
                "retention": retention_response.json() if retention_response and retention_response.status_code == 200 else None
            }
    
    except Exception as e:
        return {"success": False, "error": str(e)} 