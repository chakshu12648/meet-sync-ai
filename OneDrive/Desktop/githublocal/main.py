import os
import requests
import base64
import time
import logging
import json
import threading
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from discord.ext import commands
import discord
import nest_asyncio
from pyngrok import ngrok
from dotenv import load_dotenv
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
import asyncpg
import openai
# Required for running FastAPI and Discord bot together
nest_asyncio.apply()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Create a FastAPI app
app = FastAPI()

# Discord Bot Setup with intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Environment variables
ZOOM_CLIENT_ID = os.getenv('ZOOM_CLIENT_ID')
ZOOM_CLIENT_SECRET = os.getenv('ZOOM_CLIENT_SECRET')
ZOOM_ACCOUNT_ID = os.getenv('ZOOM_ACCOUNT_ID')
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_DB = os.getenv("POSTGRES_DB")
openai.api_key = os.getenv("OPENAI_API_KEY", "sk-n_U1FuEr4S5BmFSuab4aqP0xQTEJIxKy-BKyMqeiL-T3BlbkFJSEJMU1RcXAnLPzSCi0pVoTdoNomd6hMdhKWgcsDlgA")

# File to store refresh token
TOKEN_FILE = "token.json"

# Function to start ngrok tunnel and get updated URL
def start_ngrok():
    url = ngrok.connect(8000).public_url
    print(f"ngrok tunnel \"{url}\" -> \"http://localhost:8000\"")
    return url

# Update REDIRECT_URI
REDIRECT_URI = start_ngrok() + "/callback"

# Function to get an access token using server-to-server OAuth for Zoom
def get_access_token():
    token_url = "https://zoom.us/oauth/token"
    auth_header = base64.b64encode(f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}".encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "account_credentials",
        "account_id": ZOOM_ACCOUNT_ID
    }

    response = requests.post(token_url, headers=headers, data=data)

    if response.status_code == 200:
        return response.json()  # Contains access_token
    else:
        raise Exception(f"Failed to get access token: {response.text}")

# Function to create a Zoom meeting
def create_zoom_meeting(access_token, topic, start_time, duration):
    meeting_url = "https://api.zoom.us/v2/users/me/meetings"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    meeting_data = {
        "topic": topic,
        "type": 2,  # Scheduled meeting
        "start_time": start_time,
        "duration": duration,
        "timezone": "America/Los_Angeles",  # Change this to the user's timezone
        "agenda": "Discuss the project",
        "settings": {
            "host_video": True,
            "participant_video": True,
            "audio": "voip",
            "auto_recording": "cloud"
        }
    }

    response = requests.post(meeting_url, headers=headers, json=meeting_data)

    if response.status_code == 201:
        return response.json()  # Contains meeting info
    else:
        raise Exception(f"Failed to create Zoom meeting: {response.status_code} {response.text}")
    
async def connect_to_db():
    conn = await asyncpg.connect(
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_DB,
        host=POSTGRES_HOST
    )
    return conn

# Function to log user activity (login/logout)
async def log_user_activity(employee_id, name, user_id, action):
    conn = await connect_to_db()

    # Check if the user has an ongoing session (no logout time)
    query = """
    SELECT * FROM employee_log
    WHERE employee_id = $1 AND logout_time IS NULL
    ORDER BY login_time DESC
    LIMIT 1
    """
    result = await conn.fetchrow(query, employee_id)

    if action == "login":
        if result:
            # The user hasn't logged out yet, update the logout time first
            await conn.execute("""
                UPDATE employee_log SET logout_time = $1 WHERE id = $2
            """, datetime.utcnow(), result['id'])

        # Insert a new login entry
        await conn.execute("""
            INSERT INTO employee_log (employee_id, name, user_id, login_time)
            VALUES ($1, $2, $3, $4)
        """, employee_id, name, user_id, datetime.utcnow())

    elif action == "logout":
        if result:
            # Update the logout time for the ongoing session
            await conn.execute("""
                UPDATE employee_log SET logout_time = $1 WHERE id = $2
            """, datetime.utcnow(), result['id'])
        else:
            # If no active login session, create a new entry with both login and logout times
            await conn.execute("""
                INSERT INTO employee_log (employee_id, name, user_id, login_time, logout_time)
                VALUES ($1, $2, $3, $4, $5)
            """, employee_id, name, user_id, datetime.utcnow(), datetime.utcnow())

    await conn.close()

# Discord bot commands for login/logout
@bot.command()
async def login(ctx, employee_id: int, name: str):
    user_id = str(ctx.author.id)
    try:
        await log_user_activity(employee_id, name, user_id, "login")
        await ctx.send(f"Logged in {name} (Employee ID: {employee_id})")
    except Exception as e:
        await ctx.send(f"Error logging in: {str(e)}")

@bot.command()
async def logout(ctx):
    user_id = str(ctx.author.id)
    conn = await connect_to_db()

    # Find the employee ID associated with this user_id
    query = "SELECT employee_id FROM employee_log WHERE user_id = $1 ORDER BY login_time DESC LIMIT 1"
    result = await conn.fetchrow(query, user_id)

    if result:
        employee_id = result['employee_id']
        try:
            # Log out the user
            await log_user_activity(employee_id, None, user_id, "logout")
            
            # Fetch the updated entry with login and logout times
            time_query = """
            SELECT login_time, logout_time FROM employee_log
            WHERE employee_id = $1 AND user_id = $2
            ORDER BY login_time DESC
            LIMIT 1
            """
            time_result = await conn.fetchrow(time_query, employee_id, user_id)
            
            login_time = time_result['login_time']
            logout_time = time_result['logout_time']
            
            # Display the time details to the user
            await ctx.send(f"Employee ID: {employee_id} has logged out.\nLogin Time: {login_time}\nLogout Time: {logout_time}")
        
        except Exception as e:
            await ctx.send(f"Error logging out: {str(e)}")
    else:
        await ctx.send(f"No active session found for your user ID.")
    
    await conn.close()

    

# Function to get Google access token
def get_google_access_token(code=None):
    token_url = "https://oauth2.googleapis.com/token"
    
    # If code is provided (OAuth process), request new tokens
    if code:
        data = {
            'code': code,
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'authorization_code'
        }
    else:
        # Try to refresh token if no new code is provided
        if not os.path.exists(TOKEN_FILE):
            raise Exception("No stored refresh token found. Authenticate first.")

        with open(TOKEN_FILE, 'r') as token_file:
            token_info = json.load(token_file)
            refresh_token = token_info['refresh_token']

        data = {
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }

    response = requests.post(token_url, data=data)

    if response.status_code == 200:
        token_info = response.json()

        # Save the refresh token for future use (if new authorization)
        if 'refresh_token' in token_info:
            with open(TOKEN_FILE, 'w') as token_file:
                json.dump(token_info, token_file)

        return token_info  # Contains access_token and refresh_token
    else:
        raise Exception(f"Failed to get Google access token: {response.text}")

# Function to create a Google Meet link using the refreshed access token
def create_google_meeting(topic, start_time, duration):
    access_token_info = get_google_access_token()
    access_token = access_token_info['access_token']
    
    calendar_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # Convert start_time string to a datetime object
    start_dt = datetime.strptime(start_time, '%Y-%m-%dT%H:%M:%SZ')
    # Calculate end time by adding the duration in minutes
    end_dt = start_dt + timedelta(minutes=duration)

    meeting_data = {
        "summary": topic,
        "start": {
            "dateTime": start_dt.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',  # Format start time
            "timeZone": "UTC"
        },
        "end": {
            "dateTime": end_dt.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',  # Format end time
            "timeZone": "UTC"
        },
        "conferenceData": {
            "createRequest": {
                "requestId": "some-random-string",
                "conferenceSolutionKey": {
                    "type": "hangoutsMeet"
                }
            }
        }
    }

    response = requests.post(calendar_url, headers=headers, json=meeting_data)

    # Log the response for debugging
    logger.info(f"Google Meet creation response: {response.status_code} {response.text}")

    if response.status_code == 200:
        return response.json()  # Contains meeting info including the hangout link
    else:
        print("Response content:", response.content)  # Print the response content for debugging
        raise Exception(f"Failed to create Google Meet: {response.status_code} {response.text}")

# Discord bot command to authenticate with Google
@bot.command()
async def authenticate(ctx):
    auth_url = (
        f"https://accounts.google.com/o/oauth2/auth?response_type=code&"
        f"client_id={GOOGLE_CLIENT_ID}&redirect_uri={REDIRECT_URI}&"
        f"scope=https://www.googleapis.com/auth/calendar&"
        f"access_type=offline"
    )
    await ctx.send(f"Please authenticate by clicking [here]({auth_url})")

# FastAPI route to handle OAuth2 callback
@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    if code:
        try:
            token_info = get_google_access_token(code=code)
            return {"status": "success", "token_info": token_info}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    return {"status": "error", "message": "No code provided"}

# Discord bot command to set up a meeting by asking the user for details
@bot.command()
async def setupmeeting(ctx, channel: discord.TextChannel = None):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        # Ask for the meeting topic
        await ctx.send("What should be the topic of the meeting?")
        topic_msg = await bot.wait_for('message', check=check, timeout=60.0)
        topic = topic_msg.content

        # Ask for the start time
        await ctx.send("When should the meeting start? (Format: YYYY-MM-DDTHH:MM:SSZ)")
        start_time_msg = await bot.wait_for('message', check=check, timeout=60.0)
        start_time = start_time_msg.content

        # Ask for the duration
        await ctx.send("How long should the meeting be? (in minutes)")
        duration_msg = await bot.wait_for('message', check=check, timeout=60.0)
        duration = int(duration_msg.content)

        # Ask user for their preferred platform (Zoom or Google Meet)
        await ctx.send("Which platform would you like to use? (Zoom/Google Meet)")
        platform_msg = await bot.wait_for('message', check=check, timeout=60.0)
        platform = platform_msg.content.lower()

        if platform == "zoom":
            access_token_info = get_access_token()
            access_token = access_token_info['access_token']

            # Create the Zoom meeting with the provided details
            meeting_info = create_zoom_meeting(access_token, topic, start_time, duration)
            await ctx.send(f"Zoom meeting created! Join link: {meeting_info['join_url']}")
        elif platform == "google meet":
            # Create the Google Meet with the provided details
            meeting_info = create_google_meeting(topic, start_time, duration)
            await ctx.send(f"Google Meet link created! Join link: {meeting_info['htmlLink']}")
        else:
            await ctx.send("Invalid platform selected. Please choose either Zoom or Google Meet.")
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")
        
async def get_chatgpt_response(question):
    try:
        # Call ChatGPT API
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": question}
            ]
        )
        # Return the answer from the API response
        return response['choices'][0]['message']['content']
    
    except Exception as e:
        return f"Error interacting with ChatGPT: {str(e)}"

# Command to interact with ChatGPT
@bot.command()
async def ask(ctx, *, question):
    # Get the response from the ChatGPT API function
    answer = await get_chatgpt_response(question)
    # Send the response to the Discord channel
    await ctx.send(answer)
# Function to start FastAPI app in a separate thread
def run_fastapi():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    # Start FastAPI in a separate thread
    threading.Thread(target=run_fastapi).start()
    # Start the Discord bot
    bot.run(DISCORD_TOKEN)



