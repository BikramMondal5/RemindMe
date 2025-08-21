# Import necessary libraries
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import threading
import time
from datetime import datetime
import os

app = Flask(__name__)

reminders = []


# Hardcoded Twilio credentials
TWILIO_ACCOUNT_SID = "your-twilio-credentials"
TWILIO_AUTH_TOKEN = "your-twilio-credentials"
TWILIO_WHATSAPP_NUMBER = "your-twilio-credentials"

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def reminder_worker():
    while True:
        now = datetime.now()
        for r in reminders[:]:
            if now >= r["time"]:
                try:
                    client.messages.create(
                        body=f"⏰ Reminder: {r['msg']}",
                        from_=TWILIO_WHATSAPP_NUMBER,
                        to=r["to"]
                    )
                except Exception as e:
                    print("Failed to send reminder:", e)
                reminders.remove(r)
        time.sleep(30)

threading.Thread(target=reminder_worker, daemon=True).start()

@app.route("/", methods=["POST"])
def bot():
    user_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "")
    response = MessagingResponse()

    if user_msg.lower().startswith("remind me at"):
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
            reminders.append({
                "time": remind_time,
                "msg": msg_part,
                "to": from_number
            })
            response.message(f"Okay, I'll remind you at {remind_time.strftime('%H:%M')} {msg_part} ✅")
        except Exception as e:
            response.message("Invalid format. Use: remind me at HH:MM Your message")
    else:
        response.message("To set a reminder, send:\nremind me at HH:MM Your message")

    return str(response)

if __name__ == "__main__":
    app.run()