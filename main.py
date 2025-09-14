# main.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import pyttsx3
import speech_recognition as sr
import uuid
from datetime import datetime, timedelta
from typing import List, Optional
import re
from dateutil import parser

app = FastAPI(title="JusBook AI Voice Assistant", version="1.0.0")

# Initialize TTS engine
tts_engine = pyttsx3.init()
tts_engine.setProperty('rate', 150)
tts_engine.setProperty('volume', 0.8)

# Initialize speech recognizer
recognizer = sr.Recognizer()
microphone = sr.Microphone()

# Templates and static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Data storage (in-memory)
services_db = {}
bookings_db = {}
sessions_db = {}

# Keywords for ending session
GOODBYE_KEYWORDS = ["bye", "goodbye", "see you", "exit", "quit"]

# --- Classes ---
class Service:
    def __init__(self, name: str, duration: int, price: float, available_slots: List[str]):
        self.id = str(uuid.uuid4())
        self.name = name
        self.duration = duration
        self.price = price
        self.available_slots = available_slots
        self.created_at = datetime.now()

class Booking:
    def __init__(self, user_name: str, service_id: str, date: str, time: str):
        self.id = str(uuid.uuid4())
        self.user_name = user_name
        self.service_id = service_id
        self.date = date
        self.time = time
        self.status = "confirmed"
        self.created_at = datetime.now()

class ConversationSession:
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.state = "greeting"
        self.user_name = None
        self.selected_service = None
        self.selected_date = None
        self.selected_time = None
        self.conversation_history = []
        self.created_at = datetime.now()

class IntentClassifier:
    def __init__(self):
        self.intents = {
            'greeting': ['hi', 'hello', 'hey', 'good morning', 'good afternoon'],
            'booking': ['book', 'appointment', 'schedule', 'reserve'],
            'availability': ['available', 'slots', 'when', 'time'],
            'cancel': ['cancel', 'remove', 'delete'],
            'update': ['change', 'update', 'reschedule'],
            'show_bookings': ['show my bookings', 'my bookings', 'list bookings', 'current bookings'],
            'help': ['help', 'assist', 'what can you do'],
            'confirm': ['yes', 'confirm', 'ok', 'sure', 'correct'],
            'deny': ['no', 'cancel', 'wrong', 'incorrect']
        }

    def classify(self, text: str) -> str:
        text = text.lower().strip()
        for intent, keywords in self.intents.items():
            if any(keyword in text for keyword in keywords):
                return intent
        return 'unknown'

intent_classifier = IntentClassifier()

# --- Initialize sample services ---
def initialize_sample_data():
    haircut = Service("Haircut", 30, 25.0, ["09:00 AM", "10:00 AM", "11:00 AM", "02:00 PM", "03:00 PM", "04:00 PM"])
    consultation = Service("Consultation", 60, 50.0, ["09:00 AM", "11:00 AM", "02:00 PM", "04:00 PM"])
    massage = Service("Massage", 90, 80.0, ["09:00 AM", "11:00 AM", "02:00 PM"])
    services_db[haircut.id] = haircut
    services_db[consultation.id] = consultation
    services_db[massage.id] = massage

initialize_sample_data()

# --- Voice processing functions ---
def speak_text(text: str):
    try:
        tts_engine.say(text)
        tts_engine.runAndWait()
    except Exception as e:
        print(f"TTS Error: {e}")

def listen_for_speech(timeout: int = 5) -> Optional[str]:
    try:
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=5)
        text = recognizer.recognize_google(audio)
        return text.lower()
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return None
    except Exception as e:
        print(f"Speech recognition error: {e}")
        return None

# --- Conversation management ---
def get_response_for_state(session: ConversationSession, user_input: str) -> str:
    # End session check
    if any(word in user_input.lower() for word in GOODBYE_KEYWORDS):
        session.state = "ended"
        return "Goodbye! Thank you for using JusBook. Have a great day!"

    intent = intent_classifier.classify(user_input)

    # Show user bookings
    if intent == "show_bookings":
        user_bookings = [b for b in bookings_db.values() if b.user_name == session.user_name and b.status == "confirmed"]
        if user_bookings:
            response = "Here are your current bookings:\n"
            for b in user_bookings:
                response += f"- {services_db[b.service_id].name} on {b.date} at {b.time}\n"
            return response
        return "You have no active bookings."

    # Cancel booking
    if intent == "cancel":
        cancelled_bookings = []
        for b in bookings_db.values():
            if b.user_name == session.user_name and b.status == "confirmed":
                b.status = "cancelled"
                cancelled_bookings.append(b)
        if cancelled_bookings:
            session.state = "greeting"
            return "Your bookings have been cancelled successfully."
        return "You have no active bookings to cancel."

    # Update booking
    if intent == "update":
        for b in bookings_db.values():
            if b.user_name == session.user_name and b.status == "confirmed":
                session.selected_service = services_db[b.service_id]
                b.status = "cancelled"
                session.state = "datetime"
                return f"Your previous booking is cancelled. Let's book a new slot for {session.selected_service.name}. Which date and time do you prefer?"
        return "You have no bookings to update. Let's create a new booking."

    # Conversation flow
    if session.state == "greeting":
        return handle_greeting_state(session)
    elif session.state == "name":
        return handle_name_state(session, user_input)
    elif session.state == "service":
        return handle_service_state(session, user_input)
    elif session.state == "datetime":
        return handle_datetime_state(session, user_input)
    elif session.state == "confirmation":
        return handle_confirmation_state(session, user_input, intent)
    elif session.state == "ended":
        return "The session has ended. Please start a new session to continue."
    else:
        return "I'm sorry, I didn't understand. Could you try again?"

def handle_greeting_state(session: ConversationSession) -> str:
    session.state = "name"
    return "Welcome to JusBook! I'm your AI assistant. What's your name?"

def handle_name_state(session: ConversationSession, user_input: str) -> str:
    name = extract_name(user_input)
    if name:
        session.user_name = name
        session.state = "service"
        services_list = "\n".join([f"- {service.name} (${service.price}, {service.duration} min)" 
                                   for service in services_db.values()])
        return f"Nice to meet you, {name}! Here are our available services:\n{services_list}\n\nWhich service would you like to book?"
    return "I didn't catch your name. Could you tell me again?"

def handle_service_state(session: ConversationSession, user_input: str) -> str:
    selected_service = None
    for service in services_db.values():
        if service.name.lower() in user_input.lower():
            selected_service = service
            break
    if selected_service:
        session.selected_service = selected_service
        session.state = "datetime"
        slots = ", ".join(selected_service.available_slots)
        return f"Great choice! {selected_service.name} costs ${selected_service.price} and takes {selected_service.duration} minutes.\nAvailable slots: {slots}\nWhat date and time would you prefer? (e.g., 'tomorrow at 2 PM')"
    services_list = ", ".join([service.name for service in services_db.values()])
    return f"I didn't recognize that service. Available services: {services_list}. Which one would you like?"

def handle_datetime_state(session: ConversationSession, user_input: str) -> str:
    date, time_slot = extract_datetime(user_input)
    if date and time_slot and time_slot in session.selected_service.available_slots:
        if is_slot_available(session.selected_service.id, date, time_slot):
            session.selected_date = date
            session.selected_time = time_slot
            session.state = "confirmation"
            return f"Perfect! Here's your booking:\n\n" \
                   f"Name: {session.user_name}\n" \
                   f"Service: {session.selected_service.name}\n" \
                   f"Date: {date}\n" \
                   f"Time: {time_slot}\n" \
                   f"Duration: {session.selected_service.duration} minutes\n" \
                   f"Price: ${session.selected_service.price}\n\nShall I confirm this booking?"
        return f"Sorry, that slot is not available. Please choose from: {', '.join(session.selected_service.available_slots)}"
    return "I couldn't understand the date and time. Please try something like 'tomorrow at 2 PM'."

def handle_confirmation_state(session: ConversationSession, user_input: str, intent: str) -> str:
    if intent == "confirm":
        booking = Booking(session.user_name, session.selected_service.id, session.selected_date, session.selected_time)
        bookings_db[booking.id] = booking
        session.state = "completed"
        return f"Excellent! Your booking is confirmed!\nBooking ID: {booking.id[:8]}\nService: {session.selected_service.name}\nDate: {session.selected_date}\nTime: {session.selected_time}\nThank you for using JusBook!"
    elif intent == "deny":
        session.state = "service"
        return "No problem! Let's start over. Which service would you like?"
    return "Please say 'yes' to confirm or 'no' to start over."

# --- Utility functions ---
def extract_name(text: str) -> Optional[str]:
    text = text.strip()
    patterns = [r"my name is (\w+)", r"i'm (\w+)", r"i am (\w+)", r"call me (\w+)"]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return match.group(1).title()
    words = text.split()
    if len(words) == 1 and words[0].isalpha():
        return words[0].title()
    elif len(words) == 2 and all(word.isalpha() for word in words):
        return " ".join(word.title() for word in words)
    return None

def extract_datetime(text: str) -> tuple:
    text = text.strip()
    today = datetime.now()
    try:
        dt = parser.parse(text, fuzzy=True, default=today)
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%I:%M %p")
        return date_str, time_str
    except Exception as e:
        print(f"Date parsing error: {e}")
        fallback_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        fallback_time = "09:00 AM"
        return fallback_date, fallback_time

def is_slot_available(service_id: str, date: str, time: str) -> bool:
    for booking in bookings_db.values():
        if booking.service_id == service_id and booking.date == date and booking.time == time and booking.status == "confirmed":
            return False
    return True

# --- API routes ---
@app.get("/", response_class=HTMLResponse)
async def get_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/start-session")
async def start_session():
    session = ConversationSession()
    sessions_db[session.id] = session
    return {"session_id": session.id, "message": "Welcome to JusBook! Say Hi", "state": session.state}

@app.post("/api/send-message")
async def send_message(request: Request):
    data = await request.json()
    session_id = data.get("session_id")
    message = data.get("message", "").strip()
    if not session_id or session_id not in sessions_db:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sessions_db[session_id]
    session.conversation_history.append({"user": message})
    response = get_response_for_state(session, message)
    session.conversation_history.append({"assistant": response})
    return {"response": response, "state": session.state,
            "session_data": {"user_name": session.user_name,
                             "selected_service": session.selected_service.name if session.selected_service else None,
                             "selected_date": session.selected_date,
                             "selected_time": session.selected_time}}

@app.post("/api/voice-input")
async def process_voice_input(request: Request):
    data = await request.json()
    session_id = data.get("session_id")
    if not session_id or session_id not in sessions_db:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sessions_db[session_id]
    if session.state == "ended":
        return {"response": "The session has ended. Please start a new session.", "state": session.state}
    speech_text = listen_for_speech()
    if speech_text:
        session.conversation_history.append({"user": speech_text})
        response = get_response_for_state(session, speech_text)
        session.conversation_history.append({"assistant": response})
        return {"transcribed_text": speech_text, "response": response, "state": session.state}
    return {"error": "Could not understand speech.", "transcribed_text": None, "response": "I couldn't hear you clearly. Please try again."}

@app.get("/api/services")
async def get_services():
    return [{"id": s.id, "name": s.name, "duration": s.duration, "price": s.price, "available_slots": s.available_slots} for s in services_db.values()]

@app.post("/api/services")
async def create_service(request: Request):
    data = await request.json()
    service = Service(data["name"], data["duration"], data["price"], data["available_slots"])
    services_db[service.id] = service
    return {"id": service.id, "name": service.name, "duration": service.duration, "price": service.price, "available_slots": service.available_slots}

@app.get("/api/bookings")
async def get_bookings():
    return [{"id": b.id, "user_name": b.user_name, "service_name": services_db[b.service_id].name, "date": b.date, "time": b.time, "status": b.status} for b in bookings_db.values()]

@app.delete("/api/bookings/{booking_id}")
async def cancel_booking(booking_id: str):
    if booking_id not in bookings_db:
        raise HTTPException(status_code=404, detail="Booking not found")
    bookings_db[booking_id].status = "cancelled"
    return {"message": "Booking cancelled successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.2", port=8000)
