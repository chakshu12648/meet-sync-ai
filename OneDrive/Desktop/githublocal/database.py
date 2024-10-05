import os
import asyncpg
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_DB = os.getenv("POSTGRES_DB")

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
            await conn.execute("""UPDATE employee_log SET logout_time = $1 WHERE id = $2""", datetime.utcnow(), result['id'])

        # Insert a new login entry
        await conn.execute("""INSERT INTO employee_log (employee_id, name, user_id, login_time) VALUES ($1, $2, $3, $4)""", employee_id, name, user_id, datetime.utcnow())

    elif action == "logout":
        if result:
            # Update the logout time for the ongoing session
            await conn.execute("""UPDATE employee_log SET logout_time = $1 WHERE id = $2""", datetime.utcnow(), result['id'])
        else:
            # If no active login session, create a new entry with both login and logout times
            await conn.execute("""INSERT INTO employee_log (employee_id, name, user_id, login_time, logout_time) VALUES ($1, $2, $3, $4, $5)""", employee_id, name, user_id, datetime.utcnow(), datetime.utcnow())

    await conn.close()
