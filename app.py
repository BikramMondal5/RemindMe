# Import necessary libraries
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import threading
import time
from datetime import datetime, timedelta
import os
import re
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
import sqlite3
import atexit

app = Flask(__name__)

# Database setup
DATABASE_PATH = 'reminders.db'

def init_db():
    """Initialize the database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Create reminders table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_phone TEXT NOT NULL,
            message TEXT NOT NULL,
            scheduled_time DATETIME NOT NULL,
            reminder_type TEXT DEFAULT 'single',
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database
init_db()

user_states = {}

# Define conversation states
STATE_INITIAL = 'initial'
STATE_AWAITING_DATE = 'awaiting_date'
STATE_AWAITING_TIME = 'awaiting_time'
STATE_AWAITING_MESSAGE = 'awaiting_message'

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Twilio credentials
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def send_reminder(user_phone, message, reminder_id=None):
    """Send reminder message and update database"""
    try:
        client.messages.create(
            body=f"⏰ Reminder: {message}",
            from_=TWILIO_WHATSAPP_NUMBER,
            to=user_phone
        )
        print(f"Sent reminder to {user_phone}: {message}")
        
        # Mark reminder as sent in database
        if reminder_id:
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            cursor.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (reminder_id,))
            conn.commit()
            conn.close()
            
    except Exception as e:
        print(f"Failed to send reminder: {e}")

def save_reminder_to_db(user_phone, message, scheduled_time, reminder_type='single'):
    """Save reminder to database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO reminders (user_phone, message, scheduled_time, reminder_type)
        VALUES (?, ?, ?, ?)
    ''', (user_phone, message, scheduled_time, reminder_type))
    
    reminder_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return reminder_id

def schedule_consecutive_reminders(to_number, message, target_date, time_str):
    """Schedule multiple reminders leading up to the target date"""
    target_datetime = datetime.strptime(f"{target_date} {time_str}", "%Y-%m-%d %H:%M")
    days_until_target = (target_datetime.date() - datetime.now().date()).days
    
    reminder_dates = []
    
    if days_until_target <= 0:
        # Schedule single reminder for today/past date
        reminder_id = save_reminder_to_db(to_number, message, target_datetime)
        scheduler.add_job(
            send_reminder,
            'date',
            run_date=target_datetime,
            args=[to_number, message, reminder_id],
            id=f"reminder_{reminder_id}"
        )
        reminder_dates.append(target_datetime.strftime("%Y-%m-%d %H:%M"))
    else:
        # Schedule multiple reminders
        # First reminder: 4 days before or halfway if less than 4 days
        days_before_first = min(4, days_until_target // 2) if days_until_target > 1 else 0
        if days_before_first > 0:
            first_reminder = target_datetime - timedelta(days=days_before_first)
            reminder_id = save_reminder_to_db(to_number, f"Upcoming in {days_before_first} days: {message}", first_reminder, 'consecutive')
            scheduler.add_job(
                send_reminder,
                'date',
                run_date=first_reminder,
                args=[to_number, f"Upcoming in {days_before_first} days: {message}", reminder_id],
                id=f"reminder_{reminder_id}"
            )
            reminder_dates.append(first_reminder.strftime("%Y-%m-%d %H:%M"))
        
        # Second reminder: 2 days before
        if days_until_target > 2:
            second_reminder = target_datetime - timedelta(days=2)
            reminder_id = save_reminder_to_db(to_number, f"Coming up in 2 days: {message}", second_reminder, 'consecutive')
            scheduler.add_job(
                send_reminder,
                'date',
                run_date=second_reminder,
                args=[to_number, f"Coming up in 2 days: {message}", reminder_id],
                id=f"reminder_{reminder_id}"
            )
            reminder_dates.append(second_reminder.strftime("%Y-%m-%d %H:%M"))
        
        # Final reminder: On the day
        reminder_id = save_reminder_to_db(to_number, f"Today: {message}", target_datetime, 'consecutive')
        scheduler.add_job(
            send_reminder,
            'date',
            run_date=target_datetime,
            args=[to_number, f"Today: {message}", reminder_id],
            id=f"reminder_{reminder_id}"
        )
        reminder_dates.append(target_datetime.strftime("%Y-%m-%d %H:%M"))
    
    return reminder_dates

def load_pending_reminders():
    """Load and reschedule pending reminders from database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, user_phone, message, scheduled_time 
        FROM reminders 
        WHERE status = 'active' AND scheduled_time > datetime('now')
    ''')
    
    pending_reminders = cursor.fetchall()
    conn.close()
    
    for reminder_id, user_phone, message, scheduled_time_str in pending_reminders:
        try:
            scheduled_time = datetime.fromisoformat(scheduled_time_str)
            scheduler.add_job(
                send_reminder,
                'date',
                run_date=scheduled_time,
                args=[user_phone, message, reminder_id],
                id=f"reminder_{reminder_id}"
            )
            print(f"Rescheduled reminder {reminder_id} for {scheduled_time}")
        except Exception as e:
            print(f"Error rescheduling reminder {reminder_id}: {e}")

# Configure scheduler with persistent job store
jobstores = {
    'default': SQLAlchemyJobStore(url=f'sqlite:///{DATABASE_PATH}')
}
executors = {
    'default': ThreadPoolExecutor(20)
}
job_defaults = {
    'coalesce': False,
    'max_instances': 3
}

# Initialize scheduler with persistent storage
try:
    scheduler = BackgroundScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults
    )
    scheduler.start()
    
    # Load existing pending reminders
    load_pending_reminders()
    
    print("Scheduler started successfully with persistent storage")
except Exception as e:
    print(f"Error starting scheduler: {e}")

# Shutdown scheduler gracefully
atexit.register(lambda: scheduler.shutdown())

def parse_date(date_str):
    """Parse date from various formats"""
    date_patterns = [
        r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})',
        r'(\d{1,2})[/-](\d{1,2})',
        r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})',
        r'(\d{1,2})\s+([A-Za-z]+)',
        r'([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})',
        r'([A-Za-z]+)\s+(\d{1,2})'
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, date_str)
        if match:
            groups = match.groups()
            current_year = datetime.now().year
            
            if len(groups) == 3 and groups[2].isdigit() and len(groups[2]) == 4:
                if groups[1].isdigit():
                    day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
                else:
                    if groups[0].isdigit():
                        day, month_name, year = int(groups[0]), groups[1], int(groups[2])
                        month = get_month_number(month_name)
                    else:
                        month_name, day, year = groups[0], int(groups[1]), int(groups[2])
                        month = get_month_number(month_name)
            elif len(groups) == 2:
                if groups[1].isdigit():
                    day, month, year = int(groups[0]), int(groups[1]), current_year
                else:
                    if groups[0].isdigit():
                        day, month_name = int(groups[0]), groups[1]
                        month = get_month_number(month_name)
                    else:
                        month_name, day = groups[0], int(groups[1])
                        month = get_month_number(month_name)
                    year = current_year
            
            try:
                date_obj = datetime(year, month, day)
                return date_obj.strftime("%Y-%m-%d")
            except ValueError:
                continue
    
    return None

def get_month_number(month_name):
    """Convert month name to month number"""
    month_name = month_name.lower()
    months = {
        'jan': 1, 'january': 1, 'feb': 2, 'february': 2,
        'mar': 3, 'march': 3, 'apr': 4, 'april': 4,
        'may': 5, 'jun': 6, 'june': 6,
        'jul': 7, 'july': 7, 'aug': 8, 'august': 8,
        'sep': 9, 'september': 9, 'oct': 10, 'october': 10,
        'nov': 11, 'november': 11, 'dec': 12, 'december': 12
    }
    
    for key, value in months.items():
        if month_name.startswith(key):
            return value
    return None

def get_user_reminders(user_phone):
    """Get active reminders for a user"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT message, scheduled_time, status 
        FROM reminders 
        WHERE user_phone = ? AND status = 'active'
        ORDER BY scheduled_time
    ''', (user_phone,))
    
    reminders = cursor.fetchall()
    conn.close()
    
    return reminders

# Health check endpoint for Render
@app.route("/health", methods=["GET"])
def health_check():
    return {"status": "healthy", "scheduler_running": scheduler.running}

@app.route("/", methods=["POST"])
def bot():
    user_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "")
    response = MessagingResponse()

    if from_number not in user_states:
        user_states[from_number] = {
            'state': STATE_INITIAL,
            'reminder_data': {}
        }
    
    user_state = user_states[from_number]
    
    # Handle commands
    if user_msg.lower() == "cancel":
        user_states[from_number] = {
            'state': STATE_INITIAL,
            'reminder_data': {}
        }
        response.message("Reminder setup canceled. Send 'remind' to start a new reminder.")
        return str(response)
    
    if user_msg.lower() in ["list", "list reminders", "my reminders"]:
        reminders = get_user_reminders(from_number)
        if reminders:
            msg = "📋 Your active reminders:\n\n"
            for i, (message, scheduled_time, status) in enumerate(reminders, 1):
                dt = datetime.fromisoformat(scheduled_time)
                msg += f"{i}. {message}\n   📅 {dt.strftime('%d %b %Y at %H:%M')}\n\n"
        else:
            msg = "You have no active reminders."
        response.message(msg)
        return str(response)
    
    if user_msg.lower() in ["remind", "set reminder", "set a reminder"]:
        user_state['state'] = STATE_AWAITING_DATE
        user_state['reminder_data'] = {}
        response.message("📅 What date do you want to be reminded on? (e.g., 26 Aug 2025, 26/08/2025)")
        return str(response)
    
    # Handle conversation states
    if user_state['state'] == STATE_AWAITING_DATE:
        parsed_date = parse_date(user_msg)
        if parsed_date:
            user_state['reminder_data']['date'] = parsed_date
            user_state['state'] = STATE_AWAITING_TIME
            response.message("⏰ What time would you like to be reminded? (e.g., 14:30 or 2:30)")
        else:
            response.message("I couldn't understand that date format. Please try again with a format like:\n- 26 Aug 2025\n- 26/08/2025\n- August 26\n\nType 'cancel' to start over.")
    
    elif user_state['state'] == STATE_AWAITING_TIME:
        time_match = re.match(r'^(\d{1,2})[:h](\d{2})$', user_msg)
        if time_match:
            hour, minute = map(int, time_match.groups())
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                time_str = f"{hour:02d}:{minute:02d}"
                user_state['reminder_data']['time'] = time_str
                user_state['state'] = STATE_AWAITING_MESSAGE
                
                date_obj = datetime.strptime(user_state['reminder_data']['date'], "%Y-%m-%d")
                formatted_date = date_obj.strftime("%d %b %Y")
                
                response.message(f"📝 Finally, what would you like to be reminded about on {formatted_date} at {time_str}?")
            else:
                response.message("Invalid time. Please enter a valid time in 24-hour format (e.g., 14:30).\n\nType 'cancel' to start over.")
        else:
            response.message("I couldn't understand that time format. Please use HH:MM format (e.g., 14:30 or 2:30).\n\nType 'cancel' to start over.")
    
    elif user_state['state'] == STATE_AWAITING_MESSAGE:
        reminder_data = user_state['reminder_data']
        reminder_data['msg'] = user_msg
        
        reminder_dates = schedule_consecutive_reminders(
            from_number,
            reminder_data['msg'],
            reminder_data['date'],
            reminder_data['time']
        )
        
        target_date = datetime.strptime(f"{reminder_data['date']} {reminder_data['time']}", "%Y-%m-%d %H:%M")
        days_until = (target_date.date() - datetime.now().date()).days
        
        if days_until <= 0:
            msg = f"✅ Reminder set for today at {reminder_data['time']}:\n"
        else:
            msg = f"✅ Reminder set for {target_date.strftime('%d %b %Y')} at {reminder_data['time']}:\n"
        
        msg += f"📝 {reminder_data['msg']}\n\n"
        
        if len(reminder_dates) > 1:
            msg += "You'll be reminded on:\n"
            for date_str in reminder_dates:
                reminder_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                msg += f"- {reminder_date.strftime('%d %b')} at {reminder_date.strftime('%H:%M')}\n"
        
        response.message(msg)
        
        user_state['state'] = STATE_INITIAL
        user_state['reminder_data'] = {}
    
    else:  # STATE_INITIAL
        if user_msg.lower().startswith("remind me at"):
            try:
                parts = user_msg.split(" ", 4)
                time_part = parts[3]
                msg_part = parts[4] if len(parts) > 4 else ""
                remind_time = datetime.strptime(time_part, "%H:%M").replace(
                    year=datetime.now().year,
                    month=datetime.now().month,
                    day=datetime.now().day
                )
                
                if remind_time < datetime.now():
                    remind_time = remind_time + timedelta(days=1)
                
                reminder_id = save_reminder_to_db(from_number, msg_part, remind_time)
                scheduler.add_job(
                    send_reminder,
                    'date',
                    run_date=remind_time,
                    args=[from_number, msg_part, reminder_id],
                    id=f"reminder_{reminder_id}"
                )
                
                response.message(f"Okay, I'll remind you at {remind_time.strftime('%H:%M')} {msg_part} ✅")
            except Exception as e:
                response.message("Invalid format. Use: remind me at HH:MM Your message")
        else:
            response.message("Welcome to RemindMe! 📅\n\nCommands:\n• 'remind' - Set a new reminder\n• 'list' - View your reminders\n• 'remind me at HH:MM message' - Quick reminder\n\nI'll guide you through the process!")

    return str(response)

if __name__ == "__main__":
    app.run()


