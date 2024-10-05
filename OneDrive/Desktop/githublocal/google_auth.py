import os
import requests
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')

def authenticate_google(redirect_uri):
    return (
        f"https://accounts.google.com/o/oauth2/auth?response_type=code&"
        f"client_id={GOOGLE_CLIENT_ID}&redirect_uri={redirect_uri}&"
        f"scope=https://www.googleapis.com/auth/calendar&"
        f"access_type=offline"
    )

def get_google_access_token(code=None):
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        'code': code,
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }

    response = requests.post(token_url, data=data)
    if response.status_code == 200:
        token_info = response.json()
        return token_info  # Contains access_token and refresh_token
    else:
        raise Exception(f"Failed to get Google access token: {response.text}")

def create_google_meeting(topic, start_time, duration):
    access_token_info = get_google_access_token()
    access_token = access_token_info['access_token']
    
    # Setup Google Meet API request
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    meeting_data = {
        "summary": topic,
        "start": {
            "dateTime": start_time,
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": f"{start_time + duration}",
            "timeZone": "UTC",
        },
        "conferenceData": {
            "createRequest": {
                "requestId": "sample123",
                "conferenceSolutionKey": {
                    "type": "hangoutsMeet"
                }
            }
        }
    }

    response = requests.post("https://www.googleapis.com/calendar/v3/calendars/primary/events",
                              headers=headers,
                              json=meeting_data)

    if response.status_code == 200:
        return response.json()  # Meeting details
    else:
        raise Exception(f"Failed to create Google meeting: {response.text}")
