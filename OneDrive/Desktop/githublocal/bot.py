import os
import json
import logging
import threading
import discord
from discord.ext import commands
from fastapi import FastAPI, Request, HTTPException
from pyngrok import ngrok
from dotenv import load_dotenv
from database import connect_to_db, log_user_activity
from google_auth import authenticate_google, create_google_meeting
from zoom import get_access_token, create_zoom_meeting
import openai
import nest_asyncio

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
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
openai.api_key = os.getenv("OPENAI_API_KEY")

# Function to start ngrok tunnel and get updated URL
def start_ngrok():
    url = ngrok.connect(8000).public_url
    print(f"ngrok tunnel \"{url}\" -> \"http://localhost:8000\"")
    return url

# Update REDIRECT_URI
REDIRECT_URI = start_ngrok() + "/callback"

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
    try:
        await log_user_activity(employee_id=None, name=None, user_id=user_id, action="logout")
        await ctx.send(f"You have been logged out.")
    except Exception as e:
        await ctx.send(f"Error logging out: {str(e)}")

# Discord bot command to authenticate with Google
@bot.command()
async def authenticate(ctx):
    auth_url = authenticate_google(REDIRECT_URI)
    await ctx.send(f"Please authenticate by clicking [here]({auth_url})")

# FastAPI route to handle OAuth2 callback
@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    if code:
        try:
            token_info = authenticate_google(code)
            return {"status": "success", "token_info": token_info}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    return {"status": "error", "message": "No code provided"}

# Discord bot command to set up a meeting by asking the user for details
@bot.command()
async def setupmeeting(ctx):
    try:
        topic = await bot.wait_for('message', timeout=60.0, check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
        start_time = await bot.wait_for('message', timeout=60.0, check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
        duration = await bot.wait_for('message', timeout=60.0, check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
        platform = await bot.wait_for('message', timeout=60.0, check=lambda m: m.author == ctx.author and m.channel == ctx.channel)

        if platform.content.lower() == "zoom":
            access_token = get_access_token()
            meeting_info = create_zoom_meeting(access_token, topic.content, start_time.content, int(duration.content))
            await ctx.send(f"Zoom meeting created! Join link: {meeting_info['join_url']}")
        elif platform.content.lower() == "google meet":
            meeting_info = create_google_meeting(topic.content, start_time.content, int(duration.content))
            await ctx.send(f"Google Meet link created! Join link: {meeting_info['htmlLink']}")
        else:
            await ctx.send("Invalid platform selected. Please choose either Zoom or Google Meet.")
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

async def get_chatgpt_response(question):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": question}]
        )
        return response['choices'][0]['message']['content']
    except Exception as e:
        return f"Error interacting with ChatGPT: {str(e)}"

# Command to interact with ChatGPT
@bot.command()
async def ask(ctx, *, question):
    answer = await get_chatgpt_response(question)
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
