import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

ZOOM_API_KEY = os.getenv("ZOOM_API_KEY")
ZOOM_API_SECRET = os.getenv("ZOOM_API_SECRET")

def get_access_token():
    # Here you would typically generate a JWT or use OAuth to get an access token.
    return "your_access_token"

def create_zoom_meeting(access_token, topic, start_time, duration):
    url = "https://api.zoom.us/v2/users/me/meetings"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    meeting_data = {
        "topic": topic,
        "type": 2,  # Scheduled meeting
        "start_time": start_time,
        "duration": duration,
        "timezone": "UTC",
        "settings": {
            "host_video": True,
            "participant_video": True,
            "join_before_host": True,
            "mute_upon_entry": False,
            "waiting_room": False,
        },
    }

    response = requests.post(url, headers=headers, json=meeting_data)
    if response.status_code == 201:
        return response.json()  # Meeting details
    else:
        raise Exception(f"Failed to create Zoom meeting: {response.text}")
