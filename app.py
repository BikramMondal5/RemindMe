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

app = Flask(__name__)

reminders = []
user_states = {}

# Define conversation states
STATE_INITIAL = 'initial'
STATE_AWAITING_DATE = 'awaiting_date'
STATE_AWAITING_TIME = 'awaiting_time'
STATE_AWAITING_MESSAGE = 'awaiting_message'


# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Twilio credentials - try to get from environment variables, fall back to hardcoded values
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def send_reminder(reminder):
    try:
        client.messages.create(
            body=f"⏰ Reminder: {reminder['msg']}",
            from_=TWILIO_WHATSAPP_NUMBER,
            to=reminder["to"]
        )
        print(f"Sent reminder to {reminder['to']}: {reminder['msg']}")
    except Exception as e:
        print("Failed to send reminder:", e)

def schedule_consecutive_reminders(to_number, message, target_date, time_str):
    # Parse the target date and time
    target_datetime = datetime.strptime(f"{target_date} {time_str}", "%Y-%m-%d %H:%M")
    
    # Calculate days until the target date
    days_until_target = (target_datetime.date() - datetime.now().date()).days
    
    if days_until_target <= 0:
        # If the target date is today or in the past, just schedule one reminder
        scheduler.add_job(
            send_reminder,
            'date',
            run_date=target_datetime,
            args=[{"to": to_number, "msg": message}]
        )
        return [target_datetime.strftime("%Y-%m-%d %H:%M")]
    
    # Schedule reminders for consecutive days
    reminder_dates = []
    
    # First reminder: 4 days before or halfway to the event if less than 4 days away
    days_before_first = min(4, days_until_target // 2) if days_until_target > 1 else 0
    if days_before_first > 0:
        first_reminder = target_datetime - timedelta(days=days_before_first)
        scheduler.add_job(
            send_reminder,
            'date',
            run_date=first_reminder,
            args=[{"to": to_number, "msg": f"Upcoming in {days_before_first} days: {message}"}]
        )
        reminder_dates.append(first_reminder.strftime("%Y-%m-%d %H:%M"))
    
    # Second reminder: 2 days before if more than 2 days away
    if days_until_target > 2:
        second_reminder = target_datetime - timedelta(days=2)
        scheduler.add_job(
            send_reminder,
            'date',
            run_date=second_reminder,
            args=[{"to": to_number, "msg": f"Coming up in 2 days: {message}"}]
        )
        reminder_dates.append(second_reminder.strftime("%Y-%m-%d %H:%M"))
    
    # Final reminder: On the day of the event
    scheduler.add_job(
        send_reminder,
        'date',
        run_date=target_datetime,
        args=[{"to": to_number, "msg": f"Today: {message}"}]
    )
    reminder_dates.append(target_datetime.strftime("%Y-%m-%d %H:%M"))
    
    return reminder_dates

# Initialize the scheduler with error handling
try:
    scheduler = BackgroundScheduler()
    scheduler.start()
    print("Scheduler started successfully")
except Exception as e:
    print(f"Error starting scheduler: {e}")

def parse_date(date_str):
    """Parse date from various formats"""
    date_patterns = [
        # DD/MM/YYYY or DD-MM-YYYY
        r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})',
        # DD/MM or DD-MM (current year)
        r'(\d{1,2})[/-](\d{1,2})',
        # Month name formats
        r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})',  # 26 Aug 2025
        r'(\d{1,2})\s+([A-Za-z]+)',             # 26 Aug
        r'([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})',  # Aug 26 2025
        r'([A-Za-z]+)\s+(\d{1,2})'              # Aug 26
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, date_str)
        if match:
            groups = match.groups()
            current_year = datetime.now().year
            
            # Handle different patterns
            if len(groups) == 3 and groups[2].isdigit() and len(groups[2]) == 4:  # Full date with year
                if groups[1].isdigit():  # DD/MM/YYYY
                    day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
                else:  # DD Month YYYY or Month DD YYYY
                    if groups[0].isdigit():
                        day, month_name, year = int(groups[0]), groups[1], int(groups[2])
                        month = get_month_number(month_name)
                    else:
                        month_name, day, year = groups[0], int(groups[1]), int(groups[2])
                        month = get_month_number(month_name)
            elif len(groups) == 2:  # Date without year
                if groups[1].isdigit():  # DD/MM
                    day, month, year = int(groups[0]), int(groups[1]), current_year
                else:  # DD Month or Month DD
                    if groups[0].isdigit():
                        day, month_name = int(groups[0]), groups[1]
                        month = get_month_number(month_name)
                    else:
                        month_name, day = groups[0], int(groups[1])
                        month = get_month_number(month_name)
                    year = current_year
            
            # Validate date
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
        'jan': 1, 'january': 1,
        'feb': 2, 'february': 2,
        'mar': 3, 'march': 3,
        'apr': 4, 'april': 4,
        'may': 5,
        'jun': 6, 'june': 6,
        'jul': 7, 'july': 7,
        'aug': 8, 'august': 8,
        'sep': 9, 'september': 9,
        'oct': 10, 'october': 10,
        'nov': 11, 'november': 11,
        'dec': 12, 'december': 12
    }
    
    for key, value in months.items():
        if month_name.startswith(key):
            return value
    
    return None

@app.route("/", methods=["POST"])
def bot():
    user_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "")
    response = MessagingResponse()

    # Initialize user state if not exists
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
    
    # Always start with date when setting a reminder
    if user_msg.lower() == "remind" or user_msg.lower() == "set reminder" or user_msg.lower() == "set a reminder":
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
        # Try to parse time (HH:MM)
        time_match = re.match(r'^(\d{1,2})[:h](\d{2})$', user_msg)
        if time_match:
            hour, minute = map(int, time_match.groups())
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                time_str = f"{hour:02d}:{minute:02d}"
                user_state['reminder_data']['time'] = time_str
                user_state['state'] = STATE_AWAITING_MESSAGE
                
                # Format the date for display
                date_obj = datetime.strptime(user_state['reminder_data']['date'], "%Y-%m-%d")
                formatted_date = date_obj.strftime("%d %b %Y")
                
                response.message(f"📝 Finally, what would you like to be reminded about on {formatted_date} at {time_str}?")
            else:
                response.message("Invalid time. Please enter a valid time in 24-hour format (e.g., 14:30) or 12-hour format (e.g., 2:30).\n\nType 'cancel' to start over.")
        else:
            response.message("I couldn't understand that time format. Please use HH:MM format (e.g., 14:30 or 2:30).\n\nType 'cancel' to start over.")
    
    elif user_state['state'] == STATE_AWAITING_MESSAGE:
        # Save the reminder message and schedule reminders
        reminder_data = user_state['reminder_data']
        reminder_data['msg'] = user_msg
        
        # Schedule consecutive reminders
        reminder_dates = schedule_consecutive_reminders(
            from_number,
            reminder_data['msg'],
            reminder_data['date'],
            reminder_data['time']
        )
        
        # Format response message
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
        
        # Reset state
        user_state['state'] = STATE_INITIAL
        user_state['reminder_data'] = {}
    
    else:  # STATE_INITIAL
        if user_msg.lower().startswith("remind me at"):
            # Support for legacy format
            try:
                # Parse: "remind me at HH:MM message"
                parts = user_msg.split(" ", 4)
                time_part = parts[3]
                msg_part = parts[4] if len(parts) > 4 else ""
                remind_time = datetime.strptime(time_part, "%H:%M").replace(
                    year=datetime.now().year,
                    month=datetime.now().month,
                    day=datetime.now().day
                )
                # If time already passed today, schedule for tomorrow
                if remind_time < datetime.now():
                    remind_time = remind_time.replace(day=remind_time.day + 1)
                
                # Schedule a single reminder
                scheduler.add_job(
                    send_reminder,
                    'date',
                    run_date=remind_time,
                    args=[{"to": from_number, "msg": msg_part}]
                )
                
                response.message(f"Okay, I'll remind you at {remind_time.strftime('%H:%M')} {msg_part} ✅")
            except Exception as e:
                response.message("Invalid format. Use: remind me at HH:MM Your message")
        else:
            response.message("Welcome to RemindMe! 📅\n\nTo set a reminder with consecutive notifications, send:\n'remind' or 'set reminder'\n\nI'll guide you through setting the date, time, and message for your reminder.\n\nOr use the quick format for simple reminders:\nremind me at HH:MM Your message")

    return str(response)

if __name__ == "__main__":
    app.run()
