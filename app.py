import os
import re
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from twilio.rest import Client
from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Check for required environment variables
required_env_vars = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_NUMBER"]
missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    logger.error("Please create a .env file with these variables.")
    exit(1)

app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

# Twilio client
try:
    client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    logger.info("Twilio client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Twilio client: {str(e)}")
    exit(1)

# Store the most recent user number
latest_user_number = None

def send_whatsapp_message(to, message):
    """Send a WhatsApp message via Twilio."""
    try:
        client.messages.create(
            from_=os.getenv("TWILIO_WHATSAPP_NUMBER"),
            to=to,
            body=message
        )
        logger.info(f"Message sent successfully to {to}")
    except TwilioRestException as e:
        logger.error(f"Failed to send WhatsApp message: {str(e)}")
        if e.code == 21610:
            logger.error("This number is not opted in to receive WhatsApp messages.")
        elif e.code == 20003:
            logger.error("Authentication error. Check your Twilio credentials.")
        elif e.code == 21612:
            logger.error("The 'from' number is not a valid Twilio WhatsApp number.")
    except Exception as e:
        logger.error(f"Unexpected error when sending message: {str(e)}")

def schedule_reminder(to, minutes, reminder_text):
    """Schedule a reminder for the given user."""
    run_time = datetime.now() + timedelta(minutes=minutes)
    scheduler.add_job(send_whatsapp_message, 'date', run_date=run_time,
                      args=[to, f"⏰ Reminder: {reminder_text}"])
    print(f"Scheduled reminder for {to} in {minutes} min: {reminder_text}")

@app.route("/", methods=["GET"])
def index():
    return "WhatsApp Bot is running! Send POST requests to the /whatsapp endpoint."

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    global latest_user_number
    
    # Check if form data exists
    if not request.form:
        logger.error("No form data received in the request")
        return jsonify({"error": "No form data received"}), 400
        
    # Get message and handle potential None value
    incoming_msg = request.form.get("Body", "")
    if incoming_msg:
        incoming_msg = incoming_msg.lower()
    else:
        logger.error("No message body in the request")
        return jsonify({"error": "No message body"}), 400
        
    sender = request.form.get("From")  # WhatsApp sender number
    if not sender:
        logger.error("No sender information in the request")
        return jsonify({"error": "No sender information"}), 400
        
    logger.info(f"Received message: '{incoming_msg}' from {sender}")
    latest_user_number = sender  # Update to the latest user

    # Pattern: "remind me in 10 minutes to drink water"
    match = re.match(r"remind me in (\d+) minutes? to (.+)", incoming_msg)
    if match:
        minutes = int(match.group(1))
        task = match.group(2)
        schedule_reminder(latest_user_number, minutes, task)
        send_whatsapp_message(latest_user_number, f"✅ Got it! I will remind you in {minutes} minutes to {task}")
    else:
        send_whatsapp_message(latest_user_number, "❓ Format: 'remind me in X minutes to <task>'")

    return "OK", 200

if __name__ == "__main__":
    app.run(port=5000, debug=True)
