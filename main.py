from flask import Flask, render_template, request, flash, redirect, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import pymysql
import datetime
from zoneinfo import ZoneInfo
import calendar as cal
cal.setfirstweekday(cal.SUNDAY)
from dynaconf import Dynaconf
from flask_mail import Mail, Message
from datetime import timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import re
from collections import Counter
from flask import jsonify
from flask import session


app = Flask(__name__)

config = Dynaconf(settings_files=["settings.toml"])
app.secret_key = config.secret_key

# ---------------- EMAIL CONFIG ----------------
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USE_SSL"] = False
app.config["MAIL_USERNAME"] = config.email
app.config["MAIL_PASSWORD"] = config.email_password
app.config["MAIL_DEFAULT_SENDER"] = config.email
mail = Mail(app)



login_manager = LoginManager(app)
login_manager.login_view = "/login"


# ---------------- DATABASE ----------------
def connect_db():
    conn = pymysql.connect(
        host="db.steamcenter.tech",
        user=config.username,
        password=config.password,
        database="bookwell",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor
    )
    return conn

def generate_time_slots(start_hour=9, end_hour=17, interval=60, date=None):
    slots = []
    base_date = date or datetime.date.today()

    current = datetime.datetime.combine(base_date, datetime.time(start_hour, 0))
    end_time = datetime.datetime.combine(base_date, datetime.time(end_hour, 0))

    while current < end_time:
        slots.append(current)
        current += datetime.timedelta(minutes=interval)

    return slots


# ---------------- USER CLASS ----------------
class User:
    is_authenticated = True
    is_active = True
    is_anonymous = False

    def __init__(self, result):
        self.name = result["Name"]
        self.email = result["Email"]
        self.address = result["Address"]
        self.join = result["Joindate"]
        self.id = result["ID"]

    def get_id(self):
        return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM User WHERE ID = %s", (user_id,))
    result = cursor.fetchone()

    connection.close()

    if result is None:
        return None

    return User(result)


# ---------------- HOME ----------------
@app.route("/")
def index():
    return render_template("homepage.html.jinja")


# ---------------- DOCTORS ----------------
@app.route("/doctor", methods = ["POST"])
def doctor():
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM Doctor")
    result = cursor.fetchall()

    connection.close()

    return redirect ("/doctor", doctors=result)

@app.route("/doctor/<int:doctor_id>/reply_review", methods=["POST"])
def reply_review(doctor_id):

   
    if not session.get("doctor_logged_in"):
        flash("Please login first")
        return redirect("/doctorlogin")

   
    if session.get("doctor_id") != doctor_id:
        flash("Unauthorized access")
        return redirect("/doctorlogin")

    review_id = request.form.get("review_id")
    reply = request.form.get("reply")

    if not review_id or not reply:
        flash("Reply cannot be empty", "error")
        return redirect(f"/doctor/{doctor_id}/appointments")

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE Review
        SET Reply = %s
        WHERE ID = %s
        AND DoctorID = %s
    """, (reply, review_id, doctor_id))

    connection.commit()
    connection.close()

    flash("Reply added successfully!", "success")

    return redirect(f"/doctor/{doctor_id}/appointments")

@app.route("/doctorappoint/<int:dtr_id>/delete_review", methods=["POST"])
@login_required
def delete_review(dtr_id):

    del_id = request.form.get("del_id")

    return redirect(f"/doctorappoint/{dtr_id}")

@app.route("/doctorlogout")
def doctor_logout():

    session.clear()

    flash("Logged out successfully")

    return redirect("/doctorlogin")

@app.route("/doctorlogin", methods=["GET","POST"])
def doctor_login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        connection = connect_db()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT * FROM Doctor WHERE Email=%s",
            (email,)
        )

        doctor = cursor.fetchone()

        connection.close()

        if doctor is None:
            flash("Doctor account not found")

        elif password != doctor["Password"]:
            flash("Incorrect password")

        else:
            session.permanent = True
            session["doctor_logged_in"] = True
            session["doctor_id"] = doctor["ID"]
            session["doctor_name"] = doctor["Name"]

            flash("Doctor login successful")

            return redirect(f"/doctor/{doctor['ID']}/homepage")

    return render_template("doctorlogin.html.jinja")

@app.route("/doctor/<int:doctor_id>")
def doctor_page(doctor_id):

    connection = connect_db()
    cursor = connection.cursor()

    # ---------------- DOCTOR ----------------
    cursor.execute("SELECT * FROM Doctor WHERE ID=%s", (doctor_id,))
    doctor = cursor.fetchone()

    if not doctor:
        connection.close()
        abort(404)

    # ---------------- REVIEWS ----------------
    cursor.execute("""
        SELECT Review.*, User.Name
        FROM Review
        JOIN User ON User.ID = Review.UserID
        WHERE Review.DoctorID = %s
        ORDER BY Review.ID DESC
    """, (doctor_id,))
    reviews = cursor.fetchall()

    # ---------------- AVERAGE RATING ----------------
    cursor.execute("""
        SELECT AVG(Rating) AS avg_rating
        FROM Review
        WHERE DoctorID = %s
    """, (doctor_id,))
    avg_result = cursor.fetchone()

    average_rating = round(avg_result["avg_rating"], 1) if avg_result and avg_result["avg_rating"] else None

    # ---------------- USER INPUT ----------------
    selected_date = request.args.get("date")
    visit_type = request.args.get("visit_type", "In-Person")

    available_slots = []

    if selected_date:

        all_slots = generate_time_slots(9, 17, 60, datetime.datetime.strptime(selected_date, "%Y-%m-%d").date())

        cursor.execute("""
            SELECT Date AS booked_time
            FROM Appointment
            WHERE DoctorID = %s
            AND DATE(Date) = %s
            AND Status != 'Cancelled'
        """, (doctor_id, selected_date))

        booked = [
    row["booked_time"].strftime("%H:%M")
    for row in cursor.fetchall()
]

        available_slots = [slot for slot in all_slots if slot not in booked]

    connection.close()

    return render_template(
        "doctor.html.jinja",
        doctor=doctor,
        reviews=reviews,
        average_rating=average_rating,
        selected_date=selected_date,
        visit_type=visit_type,
        available_slots=available_slots
    )

@app.route("/doctor/<int:doctor_id>/book", methods=["POST"])
@login_required
def book_appointment(doctor_id):

    date = request.form.get("date")
    time = request.form.get("time")
    visit_type = request.form.get("visit_type", "In-Person")

    if not date or not time:
        flash("Please select date and time.", "error")
        return redirect(f"/doctor/{doctor_id}")

    start_datetime = datetime.datetime.strptime(
    f"{date} {time}", "%Y-%m-%d %H:%M"
)

    if start_datetime <= datetime.datetime.now():
        flash("You cannot book a past time.", "error")
        return redirect(f"/doctor/{doctor_id}")

    connection = connect_db()
    cursor = connection.cursor()

    # ---------------- CHECK CONFLICT ----------------
    cursor.execute("""
        SELECT * FROM Appointment
        WHERE DoctorID=%s
        AND Date=%s
        AND Status != 'Cancelled'
    """, (doctor_id, start_datetime))

    if cursor.fetchone():
        connection.close()
        flash("Slot already booked.", "error")
        return redirect(f"/doctor/{doctor_id}")

    # ---------------- INSERT ----------------
    cursor.execute("""
        INSERT INTO Appointment (DoctorID, UserID, Date, Type, Status)
        VALUES (%s, %s, %s, %s, %s)
    """, (doctor_id, current_user.id, start_datetime, visit_type, "Scheduled"))

    connection.commit()
    connection.close()

    flash("Appointment booked successfully!", "success")
    return redirect("/thanks")

@app.route("/doctor/<int:doctor_id>/remove_review", methods=["POST"])
@login_required
def remove_review(doctor_id):

    review_id = request.form.get("review_id")

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM Review
        WHERE ID = %s AND UserID = %s
    """, (review_id, current_user.id))

    connection.commit()
    connection.close()

    return redirect(f"/doctor/{doctor_id}")

@app.route("/doctor/<doc_id>/review", methods=["POST"])
@login_required
def review(doc_id):

    comment = request.form["comments"]
    ratings = request.form["rating"]

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO Review(`UserID`, `Comments`, `Rating`, `DoctorID`)
        VALUES (%s, %s, %s, %s)
    """, (current_user.id, comment, ratings, doc_id))

    connection.commit()
    connection.close()

    flash("Your review was submitted successfully!", "success")  

    return redirect(f"/doctor/{doc_id}")
     
# ---------------- APPOINTMENTS ----------------
@app.route("/appoint")
@login_required
def appoint():

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT 
            Appointment.ID, 
            Appointment.Date, 
            Appointment.Type, 
            Appointment.Status,
            Doctor.ID AS DoctorID,         
            Doctor.Name AS DoctorName, 
            Doctor.Location AS Location
        FROM Appointment
        JOIN Doctor ON Doctor.ID = Appointment.DoctorID
        WHERE UserID = %s
        AND (
            Status != 'Cancelled'
            OR Date >= NOW() - INTERVAL 1 DAY
        )
        ORDER BY Appointment.Date ASC
    """, (current_user.id,))

    appointments = cursor.fetchall()
    connection.close()

    for appt in appointments:
        if isinstance(appt["Date"], str):
            appt["Date"] = datetime.datetime.strptime(
                appt["Date"], "%Y-%m-%d %H:%M:%S"
            )

    return render_template("appoint.html.jinja", appointments=appointments)

@app.route("/suggdoctors", methods=["POST"])
@login_required
def suggest_doctors():
    date = request.form.get("date")
    category = request.form.get("category")

    if not date:
        flash("Please select a date")
        return redirect("/calendar")

    try:
        date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date format")
        return redirect("/calendar")

    connection = connect_db()
    cursor = connection.cursor()

    # Base query
    query = """
    SELECT d.*, AVG(r.Rating) AS avg_rating
    FROM Doctor d
    LEFT JOIN Review r ON d.ID = r.DoctorID
    WHERE d.ID NOT IN (
        SELECT DoctorID
        FROM DoctorAvailability
        WHERE AvailableDate = %s AND Booked = 1
    )
"""

    params = [date_obj]

    if category:
      query += " AND d.Category = %s"
      params.append(category)

    query += " GROUP BY d.ID ORDER BY d.Name"

    cursor.execute(query, tuple(params))
    doctors = cursor.fetchall()

    connection.close()

    if not doctors:
        flash("No doctors available for this selection.")
        return redirect("/calendar")

    return render_template(
        "suggestions.html.jinja",
        doctors=doctors,
        selected_date=date,
        category_filter=category
    )


@app.route("/appoint/<int:appointment_id>/delete", methods=["POST"])
@login_required
def delete_appointment(appointment_id):

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM Appointment
        WHERE ID = %s
        AND UserID = %s
        AND Status = 'Confirmed'
    """, (appointment_id, current_user.id))

    connection.commit()
    connection.close()

    flash("Appointment removed successfully.")

    return redirect("/appoint")


# ---------------- BOOK APPOINTMENT ----------------

SYMPTOM_MAP = {
    # ---------------- NEUROLOGY ----------------
"headache": ["Neurology"],
"migraine": ["Neurology"],
"dizziness": ["Neurology"],
"seizure": ["Neurology"],
"memory loss": ["Neurology"],
"numbness": ["Neurology"],
"tingling": ["Neurology"],
"blurred vision": ["Neurology"],
"fainting": ["Neurology"],
"tremors": ["Neurology"],
"balance issues": ["Neurology"],
"confusion": ["Neurology"],
"brain fog": ["Neurology"],
"slurred speech": ["Neurology"],
"difficulty walking": ["Neurology"],
"muscle weakness": ["Neurology"],
"vision problems": ["Neurology"],
"face numbness": ["Neurology"],
"nerve pain": ["Neurology"],
"burning sensation": ["Neurology"],

# ---------------- ORTHOPEDICS ----------------
"bone pain": ["Orthopedic"],
"fracture": ["Orthopedic"],
"joint pain": ["Orthopedic"],
"back pain": ["Orthopedic"],
"knee pain": ["Orthopedic"],
"shoulder pain": ["Orthopedic"],
"sprain": ["Orthopedic"],
"neck pain": ["Orthopedic"],
"hip pain": ["Orthopedic"],
"ankle pain": ["Orthopedic"],
"foot pain": ["Orthopedic"],
"elbow pain": ["Orthopedic"],
"wrist pain": ["Orthopedic"],
"muscle pain": ["Orthopedic"],
"swollen joint": ["Orthopedic"],
"arthritis": ["Orthopedic"],
"stiffness": ["Orthopedic"],
"leg pain": ["Orthopedic"],
"arm pain": ["Orthopedic"],
"torn ligament": ["Orthopedic"],
"dislocated shoulder": ["Orthopedic"],
"sports injury": ["Orthopedic"],
"spine pain": ["Orthopedic"],
"scoliosis": ["Orthopedic"],

# ---------------- CARDIOLOGY ----------------
"chest pain": ["Cardiology"],
"heart pain": ["Cardiology"],
"palpitations": ["Cardiology"],
"high blood pressure": ["Cardiology"],
"hypertension": ["Cardiology"],
"shortness of breath": ["Cardiology"],
"fainting": ["Cardiology"],
"swelling": ["Cardiology"],
"rapid heartbeat": ["Cardiology"],
"irregular heartbeat": ["Cardiology"],
"slow heartbeat": ["Cardiology"],
"heart racing": ["Cardiology"],
"chest tightness": ["Cardiology"],
"fatigue": ["Cardiology"],
"dizziness": ["Cardiology"],
"cold sweats": ["Cardiology"],
"arm numbness": ["Cardiology"],
"jaw pain": ["Cardiology"],
"left arm pain": ["Cardiology"],
"ankle swelling": ["Cardiology"],
"fluid retention": ["Cardiology"],
"heart murmur": ["Cardiology"],
"passing out": ["Cardiology"],

# ---------------- PULMONOLOGY ----------------
"cough": ["Pulmonary"],
"breathing": ["Pulmonary"],
"shortness of breath": ["Pulmonary"],
"asthma": ["Pulmonary"],
"wheezing": ["Pulmonary"],
"lung pain": ["Pulmonary"],
"chronic cough": ["Pulmonary"],
"chest congestion": ["Pulmonary"],
"tight chest": ["Pulmonary"],
"trouble breathing": ["Pulmonary"],
"pain breathing": ["Pulmonary"],
"sleep apnea": ["Pulmonary"],
"snoring": ["Pulmonary"],
"bronchitis": ["Pulmonary"],
"pneumonia": ["Pulmonary"],
"coughing blood": ["Pulmonary"],
"mucus": ["Pulmonary"],
"phlegm": ["Pulmonary"],
"respiratory infection": ["Pulmonary"],
"low oxygen": ["Pulmonary"],
"lung infection": ["Pulmonary"],

# ---------------- GENERAL ----------------
"fever": ["General Medicine"],
"fatigue": ["General Medicine"],
"weakness": ["General Medicine"],
"body aches": ["General Medicine"],
"chills": ["General Medicine"],
"night sweats": ["General Medicine"],
"dehydration": ["General Medicine"],
"infection": ["General Medicine"],
"weight loss": ["General Medicine"],
"weight gain": ["General Medicine"],
"allergic reaction": ["General Medicine"],
}
SPECIALIST_GUIDE = {
    "Cardiology": {
        "urgency": "high",
        "message": "Possible heart-related issue. Seek care within 24 hours or immediately if severe."
    },
    "Pulmonary": {
        "urgency": "medium",
        "message": "Breathing-related symptoms detected. Schedule a visit soon."
    },
    "Neurology": {
        "urgency": "medium",
        "message": "Neurological symptoms detected. Consider seeing a specialist listed below."
    },
    "Orthopedic": {
        "urgency": "low",
        "message": "Musculoskeletal issue likely. Book a routine appointment."
    }
}

def extract_keywords(text):
    text = text.lower()
    return re.findall(r'\b\w+\b', text)

EMERGENCY_KEYWORDS = [
    "chest pain",
    "can't breathe",
    "cannot breathe",
    "severe bleeding",
    "stroke",
    "fainting",
    "unconscious"
]

def analyze_symptoms(user_input):
    user_input = user_input.lower()

    # ---------------- EMERGENCY CHECK ----------------
    for keyword in EMERGENCY_KEYWORDS:
        if keyword in user_input:
            return {
                "specialists": [
                    {"name": "Emergency Care", "confidence": 1.0}
                ],
                "urgency": "critical",
                "message": "⚠️ This may be an emergency. Seek immediate medical attention immediately."
            }

    words = extract_keywords(user_input)
    category_scores = Counter()

    # ---------------- MATCH SYMPTOMS ----------------
    for symptom, categories in SYMPTOM_MAP.items():
        symptom_lower = symptom.lower()
        symptom_words = symptom_lower.split()

        # Match full phrase OR partial words
        if any(word in user_input for word in symptom_words):
            for category in categories:
                category_scores[category] += 1

    # ---------------- NO MATCH ----------------
    if not category_scores:
        return {
            "specialists": [
                {"name": "General Physician", "confidence": 0.3}
            ],
            "urgency": "low",
            "message": "Symptoms unclear. Consider a general consultation."
        }

    # ---------------- RANK RESULTS ----------------
    total = sum(category_scores.values())

    ranked = [
        {
            "name": category,
            "confidence": round(score / total, 2)
        }
        for category, score in category_scores.most_common()
    ]

    top_category = ranked[0]["name"]
    guide = SPECIALIST_GUIDE.get(top_category, {
        "urgency": "low",
        "message": "Consider consulting a doctor."
    })

    return {
        "specialists": ranked,
        "urgency": guide["urgency"],
        "message": guide["message"]
    }
@app.route("/doctorsearch", methods=["GET"])
def doctorsearch():

    search_query = request.args.get("q", "")
    category_filter = request.args.get("category", "")
    insurance_filter = request.args.get("insurance", "").strip().lower()
    symptom_input = request.args.get("symptoms", "").lower()

    # ---------------- AI RESULT ----------------
    result = None
    if symptom_input:
        result = analyze_symptoms(symptom_input)

    matched_categories = set()

    if result and "specialists" in result:
        top_specialists = result["specialists"][:2]
        matched_categories = {spec["name"] for spec in top_specialists}

    # ---------------- DATABASE ----------------
    connection = connect_db()
    cursor = connection.cursor()

    sql = """
        SELECT d.*, AVG(r.Rating) as avg_rating
        FROM Doctor d
        LEFT JOIN Review r ON d.ID = r.DoctorID
        WHERE 1=1
    """
    params = []

    if search_query:
        sql += " AND d.Name LIKE %s"
        params.append(f"%{search_query}%")

    if category_filter:
        sql += " AND d.Category = %s"
        params.append(category_filter)

    if insurance_filter:
        sql += " AND LOWER(d.Insurance) LIKE %s"
        params.append(f"%{insurance_filter}%")

    if matched_categories:
        placeholders = ", ".join(["%s"] * len(matched_categories))
        sql += f" AND d.Category IN ({placeholders})"
        params.extend(list(matched_categories))

    sql += " GROUP BY d.ID ORDER BY d.Name"

    cursor.execute(sql, params)
    doctors = cursor.fetchall()

    connection.close()

    return render_template(
        "doctorsearch.html.jinja",
        doctors=doctors,
        search_query=search_query,
        category_filter=category_filter,
        symptom_input=symptom_input,
        recommended_categories=list(matched_categories),
        result=result,
         SYMPTOM_MAP=SYMPTOM_MAP
    )
# ------------ EMERGENCY BOOK ----------------
@app.route("/auto-book", methods=["POST"])
@login_required
def auto_book():

    category = request.form.get("category")

    connection = connect_db()
    cursor = connection.cursor()

    # Get all doctors in that category
    cursor.execute("""
        SELECT ID, Name
        FROM Doctor
        WHERE Category = %s
    """, (category,))
    doctors = cursor.fetchall()

    now = datetime.datetime.now()
    best_option = None

    for doc in doctors:
        doctor_id = doc["ID"]

        # Check next 3 days
        for i in range(3):
            date = (now + datetime.timedelta(days=i)).date()

            # Your existing time slots
            slots = [f"{hour:02d}:00" for hour in range(9, 17)]

            for slot in slots:
                slot_time = datetime.datetime.strptime(
                    f"{date} {slot}", "%Y-%m-%d %H:%M"
                )

                if slot_time <= now:
                    continue

                # Check if slot already booked
                cursor.execute("""
                    SELECT * FROM Appointment
                    WHERE DoctorID = %s
                    AND Date = %s
                    AND Status != 'Cancelled'
                """, (doctor_id, slot_time))

                if not cursor.fetchone():
                    best_option = {
                        "doctor_id": doctor_id,
                        "doctor_name": doc["Name"],
                        "time": slot_time
                    }
                    break

            if best_option:
                break
        if best_option:
            break

    connection.close()


    if not best_option:
        flash("No available doctors found soon.")
        return redirect("/doctorsearch")

    return render_template(
        "preview_booking.html.jinja",
        option=best_option,
        category=category
    )

@app.route("/auto-book-chat", methods=["POST"])
def auto_book_chat():

    connection = connect_db()
    cursor = connection.cursor()

    # Get first available doctor
    cursor.execute("""
        SELECT *
        FROM Doctor
        ORDER BY ID
        LIMIT 1
    """)

    doctor = cursor.fetchone()

    if not doctor:
        return jsonify({
            "success": False
        })

    # appointment time = 1 hour from now
    appointment_time = datetime.datetime.now() + datetime.timedelta(hours=1)

    connection.close()

    return jsonify({
        "success": True,
        "doctor": doctor["Name"],
        "date": appointment_time.strftime("%Y-%m-%d"),
        "time": appointment_time.strftime("%H:%M")
    })

@app.route("/confirm-auto-book", methods=["POST"])
@login_required
def confirm_auto_book():

    doctor_id = request.form.get("doctor_id")
    time = request.form.get("time")

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO Appointment (DoctorID, UserID, Date, Type, Status)
        VALUES (%s, %s, %s, %s, %s)
    """, (doctor_id, current_user.id, time, "Emergency", "Scheduled"))

    connection.commit()
    connection.close()

    flash("Emergency appointment booked successfully.")
    return redirect("/appoint")

BODY_PARTS = ["chest", "head", "back", "leg", "arm", "stomach", "throat"]
DURATIONS = ["day", "days", "week", "weeks", "month", "months"]
SEVERITY = ["mild", "moderate", "severe", "sharp", "dull"]

EMERGENCY_KEYWORDS = [
    "chest pain", "shortness of breath", "stroke",
    "fainting", "can't breathe", "severe chest"
]

QUESTIONS = [
    ("pain_location", "Where exactly is the pain located?"),
    ("duration", "How long have you had this?"),
    ("severity", "How severe is it (mild, moderate, severe)?"),
    ("other_symptoms", "Any other symptoms? (fever, nausea, etc.)")
]

CASUAL_MESSAGES = [
    "hi",
    "hello",
    "hey",
    "help",
    "thanks",
    "thank you",
    "good morning",
    "good afternoon"
]

# ---------------- HELPERS ----------------
def extract_info(message, chat):
    data = {}
    message = message.lower().strip()

    # ---------------- BODY PART ----------------
    for part in BODY_PARTS:
        if part in message:
            data["pain_location"] = part

    # ---------------- DURATION ----------------
    for d in DURATIONS:
        if d in message:
            data["duration"] = message

    # ---------------- SEVERITY ----------------
    for s in SEVERITY:
        if s in message:
            data["severity"] = s

    # ---------------- OTHER SYMPTOMS (FIXED) ----------------
    if (
        chat.get("pain_location")
        and chat.get("duration")
        and chat.get("severity")
        and not chat.get("other_symptoms")
    ):
        if message in ["no", "none", "nope", "nothing", "nah"]:
            data["other_symptoms"] = "none"
        else:
            data["other_symptoms"] = message

    return data


def analyze_chat_symptoms(context):
    context = context.lower()

    if "chest" in context:
        return {
            "specialist": "Cardiologist",
            "advice": "Chest-related symptoms should be evaluated carefully."
        }

    if "head" in context:
        return {
            "specialist": "Neurologist",
            "advice": "Head pain may relate to migraines or neurological issues."
        }

    if "back" in context:
        return {
            "specialist": "Orthopedic Doctor",
            "advice": "Back pain is often muscle or spine related."
        }

    return {
        "specialist": "General Physician",
        "advice": "A general check-up is recommended."
    }

# ---------------- ROUTES ----------------
@app.route("/reset-chat")
def reset_chat():
    session.pop("chat", None)
    return "", 200


@app.route("/chat-symptoms", methods=["POST"])
def chat_symptoms():

    try:
        data = request.get_json(force=True) or {}
        message = data.get("message", "").lower().strip()

        # ---------------- CASUAL CHAT ----------------
        greetings = ["hi", "hello", "hey", "yo"]
        thanks = ["thanks", "thank you"]
        
        if message in greetings:
            return jsonify({
                "reply": "Hi! I can help you check symptoms, find doctors, and book appointments.",
                "show_booking": False
            })

        if message in thanks:
            return jsonify({
                "reply": "You're welcome!",
                "show_booking": False
            })

        if "help" in message:
            return jsonify({
                "reply": "Tell me your symptoms or ask me to help book an appointment.",
                "show_booking": False
            })

        # ---------------- APPOINTMENT HELP ----------------
        if "appointment" in message or "book" in message:

            chat = session.get("chat", {})

            chat["booking_mode"] = True

            session["chat"] = chat

            return jsonify({
                    "reply": "Sure. What type of doctor are you looking for?",
                    "show_booking": False
         })
        # ---------------- INIT CHAT ----------------
        if "chat" not in session:

            session["chat"] = {
                "step": 0,
                "history": [],
                "symptom": "",
                "duration": "",
                "severity": "",
                "other_symptoms": ""
            }

        chat = session["chat"]
        # ---------------- BOOKING MODE ----------------
        if chat.get("booking_mode"):

                    doctor_map = {
                        "cardio": "Cardiologist",
                        "cardiologist": "Cardiologist",
                        "heart": "Cardiologist",

                        "neuro": "Neurologist",
                        "neurologist": "Neurologist",
                        "brain": "Neurologist",

                        "ortho": "Orthopedic Doctor",
                        "orthopedic": "Orthopedic Doctor",
                        "bone": "Orthopedic Doctor",
                        "back": "Orthopedic Doctor",

                        "pulmonary": "Pulmonary Doctor",
                        "lung": "Pulmonary Doctor",
                        "breathing": "Pulmonary Doctor"
                    }

                    matched = None

                    for key, value in doctor_map.items():
                        if key in message:
                            matched = value
                            break

                    if matched:
                        chat["booking_mode"] = False
                        session["chat"] = chat

                        return jsonify({
                            "reply": f"Okay — I can help you book with a {matched}. Click below to find appointments.",
                            "show_booking": True,
                            "category": matched
                        })

                    return jsonify({
                        "reply": "Please enter a doctor type like cardiologist, neurologist, orthopedic, or pulmonary.",
                        "show_booking": False
                    })

        chat["history"].append(message)

        # ---------------- STEP 0 ----------------
        if chat["step"] == 0:

            chat["symptom"] = message
            chat["step"] = 1

            session["chat"] = chat

            return jsonify({
                "reply": "How long have you had this?",
                "show_booking": False
            })

        # ---------------- STEP 1 ----------------
        if chat["step"] == 1:

            chat["duration"] = message
            chat["step"] = 2

            session["chat"] = chat

            return jsonify({
                "reply": "How severe is it? (mild, moderate, severe)",
                "show_booking": False
            })

        # ---------------- STEP 2 ----------------
        if chat["step"] == 2:

            chat["severity"] = message
            chat["step"] = 3

            session["chat"] = chat

            return jsonify({
                "reply": "Any other symptoms?",
                "show_booking": False
            })

        # ---------------- STEP 3 ----------------
        if chat["step"] == 3:

            if message in ["no", "none", "nope", "nah"]:
                chat["other_symptoms"] = "none"
            else:
                chat["other_symptoms"] = message

            # ---------------- ANALYSIS ----------------
            context = " ".join(chat["history"]).lower()

            if any(word in context for word in [
                "chest pain",
                "palpitations",
                "heart",
                "blood pressure"
            ]):

                specialist = "Cardiologist"
                advice = "Heart-related symptoms should be checked soon."

            elif any(word in context for word in [
                "headache",
                "migraine",
                "seizure",
                "memory",
                "dizziness"
            ]):

                specialist = "Neurologist"
                advice = "Neurological symptoms may need further evaluation."

            elif any(word in context for word in [
                "back pain",
                "knee pain",
                "joint pain",
                "fracture",
                "sprain"
            ]):

                specialist = "Orthopedic Doctor"
                advice = "This may be muscle, joint, or spine related."

            elif any(word in context for word in [
                "cough",
                "whooping cough",
                "asthma",
                "breathing",
                "shortness of breath"
            ]):

                specialist = "Pulmonary Doctor"
                advice = "Breathing symptoms should be evaluated."

            else:

                specialist = "General Physician"
                advice = "A general medical consultation is recommended."

            # ---------------- RESET ----------------
            session.pop("chat", None)

            return jsonify({
                "reply": f"Based on your symptoms, you may need a {specialist}. {advice}",
                "show_booking": True,
                "category": specialist
            })

    except Exception as e:

        print("CHAT ERROR:", e)

        return jsonify({
            "reply": "Sorry, something went wrong. Please try again.",
            "show_booking": False
        })
@app.route("/calendar")
@login_required
def calendar_view():

    connection = connect_db()
    cursor = connection.cursor()

    today = datetime.date.today()

    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month

    # ---------------- HANDLE MONTH BOUNDS ----------------
    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1

    # ---------------- APPOINTMENTS ----------------
    cursor.execute("""
        SELECT ID, Date, Type, Status
        FROM Appointment
        WHERE UserID = %s
        AND MONTH(Date) = %s
        AND YEAR(Date) = %s
        AND Status != 'Cancelled'
    """, (current_user.id, month, year))

    appointments = cursor.fetchall()

    # ---------------- PERSONAL EVENTS ----------------
    cursor.execute("""
        SELECT ID, Title, EventDate
        FROM PersonalEvent
        WHERE UserID = %s
        AND MONTH(EventDate) = %s
        AND YEAR(EventDate) = %s
    """, (current_user.id, month, year))

    personal_events = cursor.fetchall()

    connection.close()

    # ---------------- BUILD EVENTS DICTIONARY ----------------
    events = {}

    # -------- PERSONAL EVENTS --------
    for event in personal_events:
        event_date = event["EventDate"]

        if isinstance(event_date, str):
            event_date = datetime.datetime.strptime(
                event_date, "%Y-%m-%d %H:%M:%S"
            )

        key = event_date.strftime("%Y-%m-%d")

        if key not in events:
            events[key] = []

        events[key].append({
            "ID": event["ID"],
            "Type": event["Title"],
            "Status": "Personal",
            "Date": event_date,
            "Source": "personal"
        })

    # -------- APPOINTMENTS --------
    for appt in appointments:
        appt_date = appt["Date"]

        if isinstance(appt_date, str):
            appt_date = datetime.datetime.strptime(
                appt_date, "%Y-%m-%d %H:%M:%S"
            )

        key = appt_date.strftime("%Y-%m-%d")

        if key not in events:
            events[key] = []

        events[key].append({
            "ID": appt["ID"],
            "Type": appt["Type"],
            "Status": appt["Status"],
            "Date": appt_date,
            "Source": "appointment"
        })

    # ---------------- SORT EVENTS BY TIME ----------------
    for date in events:
        events[date].sort(key=lambda x: x["Date"])

    # ---------------- CALENDAR GRID ----------------
    month_calendar = cal.monthcalendar(year, month)
    month_name = cal.month_name[month]

    return render_template(
        "calendar.html.jinja",
        calendar=month_calendar,
        events=events,
        year=year,
        month=month,
        month_name=month_name,
        today=today.strftime("%Y-%m-%d"),
        timedelta=timedelta
    )

@app.route("/delete-event/<int:event_id>", methods=["POST"])
@login_required
def delete_event(event_id):
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM PersonalEvent
        WHERE ID = %s AND UserID = %s
    """, (event_id, current_user.id))

    connection.commit()
    connection.close()

    flash("Event deleted successfully!", "success")
    return redirect("/calendar")


@app.route("/appoint/<int:appointment_id>/cancel", methods=["POST"])
@login_required
def cancel_appointment(appointment_id):

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM Appointment
        WHERE ID = %s AND UserID = %s
    """, (appointment_id, current_user.id))

    connection.commit()
    connection.close()

    flash("Appointment has been cancelled.", "success")

    return redirect("/appoint")

@app.route("/appoint/<int:appointment_id>/attend", methods=["POST"])
@login_required
def mark_attended(appointment_id):
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE `Appointment`
        SET `Status` = 'Confirmed'
        WHERE `ID` = %s AND `UserID` = %s
    """, (appointment_id, current_user.id))

    connection.close()
    flash("Appointment marked as attended.")
    return redirect("/appoint")

@app.route("/add-event", methods=["POST"])
@login_required
def add_event():

    title = request.form.get("title")
    date = request.form.get("date")
    time = request.form.get("time")

    # ---------------- VALIDATION ----------------
    if not title or not date or not time:
        flash("Please fill all fields")
        return redirect("/calendar")

    # ---------------- SAFE DATETIME PARSE ----------------
    try:
        event_datetime = datetime.datetime.strptime(
            f"{date} {time}", "%Y-%m-%d %H:%M"
        )
    except ValueError:
        flash("Invalid date or time format")
        return redirect("/calendar")

    # ---------------- DATABASE INSERT ----------------
    connection = connect_db()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            INSERT INTO PersonalEvent (UserID, Title, EventDate)
            VALUES (%s, %s, %s)
        """, (current_user.id, title, event_datetime))

        connection.commit()

    except Exception as e:
        connection.rollback()
        print("ERROR inserting event:", e)
        flash("Failed to add event")
        return redirect("/calendar")

    finally:
        connection.close()

    flash("Event added successfully!")
    return redirect("/calendar")
    

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        connection = connect_db()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT * FROM User WHERE Email = %s",
            (email,)
        )
        result = cursor.fetchone()

        connection.close()

        if result is None:
            flash("No account found", "error")

        elif password != result["Password"]:
            flash("Wrong password", "error")

        else:
            login_user(User(result))
            flash(f"Welcome back, {result['Name']}!", "success")  
            return redirect("/calendar")

    return render_template("login.html.jinja")


# ---------------- SIGNUP ----------------
@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        confirm = request.form["confirm_password"]
        address = request.form["address"]

        if password != confirm:
            flash("Passwords do not match")

        elif len(password) < 8:
            flash("Password too short")

        else:

            connection = connect_db()
            cursor = connection.cursor()

            try:

                cursor.execute("""
                    INSERT INTO User (Name, Password, Email, Address)
                    VALUES (%s, %s, %s, %s)
                """, (name, password, email, address))

                connection.commit()

            except pymysql.err.IntegrityError:
                flash("Email already exists")

            connection.close()

            return redirect("/login")

    return render_template("signup.html.jinja")


# ---------------- LOGOUT ----------------
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")



# ---------------- DOCTORS SIDE OF THINGS ----------------
@app.route("/doctor/<int:doctor_id>/contact", methods=["GET", "POST"])
def doctor_contact(doctor_id):
    connection = connect_db()
    cursor = connection.cursor()

    # Get doctor info
    cursor.execute("SELECT * FROM Doctor WHERE ID=%s", (doctor_id,))
    doctor = cursor.fetchone()

    if not doctor:
        connection.close()
        abort(404)

    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        message = request.form.get("message")

        if not name or not email or not message:
            flash("Please fill in all fields.", "error")
        else:
            
            print(f"Message for Dr. {doctor['Name']} from {name} ({email}): {message}")
            flash("Your message has been sent successfully!, we will respond shortly.", "success")
            return redirect(f"/doctor/{doctor_id}/contact")

    connection.close()
    return render_template("doctorcontact.html.jinja", doctor=doctor)


@app.route("/doctorlogin", methods=["GET","POST"])
def doctor_loginN():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        connection = connect_db()
        cursor = connection.cursor()

        cursor.execute("SELECT * FROM Doctor WHERE Email=%s", (email,))
        doctor = cursor.fetchone()

        connection.close()

        if doctor is None:
            flash("Doctor account not found")

        elif password != doctor["Password"]:
            flash("Incorrect password")

        else:
            flash("Doctor login successful")
            return redirect(f"/doctor/{doctor['ID']}/homepage")

    return render_template("doctorlogin.html.jinja")


@app.route("/doctor/<int:doctor_id>/homepage")
def doctor_dashboard(doctor_id):

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM Doctor WHERE ID=%s", (doctor_id,))
    doctor = cursor.fetchone()

    if not doctor:
        connection.close()
        abort(404)

    cursor.execute("""
    SELECT Appointment.ID, Appointment.Date, Appointment.Type, Appointment.Status,
           User.Name AS PatientName
    FROM Appointment
    JOIN User ON User.ID = Appointment.UserID
    WHERE Appointment.DoctorID=%s
      AND Appointment.Status != 'Cancelled'
    ORDER BY Appointment.Date
""", (doctor_id,))

    appointments = cursor.fetchall()

    connection.close()

    return render_template(
        "doctorhomepage.html.jinja",
        doctor=doctor,
        appointments=appointments
    )

@app.route("/doctor/<int:doctor_id>/appointments", methods=["GET","POST"])
def doctor_appointments(doctor_id):

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM Doctor WHERE ID=%s", (doctor_id,))
    doctor = cursor.fetchone()

    if not doctor:
        connection.close()
        abort(404)

    if request.method == "POST":

        action = request.form.get("action")
        appointment_id = request.form.get("appointment_id")

        if action == "cancel":

            cursor.execute("""
                UPDATE Appointment
                SET Status='Cancelled'
                WHERE ID=%s AND DoctorID=%s
            """, (appointment_id, doctor_id))

            flash("Appointment cancelled")

       

    cursor.execute("""
        SELECT Appointment.ID, Appointment.Date, Appointment.Type, Appointment.Status,
               User.Name AS PatientName
        FROM Appointment
        JOIN User ON User.ID = Appointment.UserID
        WHERE Appointment.DoctorID=%s
        ORDER BY Appointment.Date
    """, (doctor_id,))

    appointments = cursor.fetchall()

    cursor.execute("""
    SELECT Review.*, User.Name AS PatientName
    FROM Review
    JOIN User ON User.ID = Review.UserID
    WHERE Review.DoctorID = %s
    ORDER BY Review.ID DESC
""", (doctor_id,))

    reviews = cursor.fetchall()

    connection.close()

    return render_template(
    "doctorappoint.html.jinja",
    doctor=doctor,
    appointments=appointments,
    reviews=reviews
)




@app.route("/doctor/<int:doctor_id>/calendar")
def doctor_calendar(doctor_id):

    today = datetime.date.today()

    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month

    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1

    month_name = cal.month_name[month]

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM Doctor WHERE ID=%s", (doctor_id,))
    doctor = cursor.fetchone()

    cursor.execute("""
        SELECT Date, Type, Status, User.Name AS PatientName
        FROM Appointment
        JOIN User ON User.ID = Appointment.UserID
        WHERE DoctorID=%s
        AND MONTH(Date)=%s
        AND YEAR(Date)=%s
    """, (doctor_id, month, year))

    appointments = cursor.fetchall()

    cursor.execute("""
        SELECT AvailableDate
        FROM DoctorAvailability
        WHERE DoctorID=%s AND Booked=1
    """, (doctor_id,))

    blocked = cursor.fetchall()
    connection.close()

    events = {}

    for appt in appointments:
        appt_date = appt["Date"]

        if isinstance(appt_date, str):
            appt_date = datetime.datetime.strptime(
                appt_date, "%Y-%m-%d %H:%M:%S"
            )

        key = appt_date.strftime("%Y-%m-%d")
        events.setdefault(key, []).append(appt)


    for date in events:
        events[date].sort(key=lambda x: x["Date"])

    blocked_dates = [
        b["AvailableDate"].strftime("%Y-%m-%d")
        for b in blocked
    ]

    month_calendar = cal.monthcalendar(year, month)

    return render_template(
        "doctorcalendar.html.jinja",
        doctor=doctor,
        calendar=month_calendar,
        events=events,
        blocked_dates=blocked_dates,
        year=year,
        month=month,
        month_name=month_name,
        today=today.strftime("%Y-%m-%d")
    )


@app.route("/doctor/<int:doctor_id>/block-date", methods=["POST"])
def block_date(doctor_id):

    date = request.form.get("date")

    if not date:
        flash("Please select a date")
        return redirect(f"/doctor/{doctor_id}/calendar")


    selected_date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    if selected_date < datetime.date.today():
        flash("Cannot block a past date")
        return redirect(f"/doctor/{doctor_id}/calendar")

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM DoctorAvailability
        WHERE DoctorID=%s AND AvailableDate=%s
    """, (doctor_id, date))

    if cursor.fetchone():
        connection.close()
        flash("Date already blocked")
        return redirect(f"/doctor/{doctor_id}/calendar")

    cursor.execute("""
        INSERT INTO DoctorAvailability (DoctorID, AvailableDate, Booked)
        VALUES (%s, %s, 1)
    """, (doctor_id, date))

    cursor.execute("""
        SELECT Appointment.ID, Appointment.Date,
               User.Email, User.Name,
               Doctor.Name AS DoctorName
        FROM Appointment
        JOIN User ON User.ID = Appointment.UserID
        JOIN Doctor ON Doctor.ID = Appointment.DoctorID
        WHERE Appointment.DoctorID = %s
        AND DATE(Appointment.Date) = %s
        AND Appointment.Status = 'Scheduled'
    """, (doctor_id, date))

    appointments_to_cancel = cursor.fetchall()

    
    cursor.execute("""
        UPDATE Appointment
        SET Status = 'Cancelled'
        WHERE DoctorID = %s
        AND DATE(Date) = %s
        AND Status = 'Scheduled'
    """, (doctor_id, date))

    connection.commit()
    connection.close()

   
    for appt in appointments_to_cancel:
        send_cancellation_email(
            appt["Email"],
            appt["DoctorName"],
            appt["Date"],
            appt["Name"]
        )

    flash("Date blocked and affected appointments cancelled.")
    return redirect(f"/doctor/{doctor_id}/calendar")

def send_cancellation_email(email, doctor_name, appointment_time, patient_name):
    with app.app_context():
        msg = Message(
            subject="BookWell Appointment Cancellation",
            recipients=[email],
        )

        msg.body = f"""
Dear {patient_name},

We regret to inform you that your upcoming appointment scheduled through BookWell has been cancelled due to the doctor's unavailability.

Please find the details of the cancelled appointment below:

Doctor: Dr. {doctor_name}
Date: {appointment_time.strftime('%Y-%m-%d')}
Time: {appointment_time.strftime('%H:%M')}

We sincerely apologize for any inconvenience this may cause.

We encourage you to log in to your BookWell account to reschedule your appointment at a time that works best for you.

If you have any questions or need assistance, please do not hesitate to contact our support team.

Thank you for your understanding.

Warm regards,  
The BookWell Team
"""
        try:
            mail.send(msg)
            print("Cancellation email sent successfully.")
        except Exception as e:
            print(f"Failed to send cancellation email: {e}")

# ---------------- CONTACT ----------------
@app.route("/contact", methods=["GET", "POST"])
def contact():

    if request.method == "POST":

        name = request.form.get("name")
        email = request.form.get("email")
        message = request.form.get("message")

        if not name or not email or not message:
            flash("Please fill all fields")
            return redirect("/contact")

        print(f"{name} ({email}) sent message: {message}")

        flash("Message sent successfully")
        return redirect("/thankscontact")

    return render_template("contactus.html.jinja")


@app.route("/thanks")
def thanks():
    return render_template("thanks.html.jinja")


@app.route("/thankscontact")
def thankscontact():
    return render_template("thankscontact.html.jinja")


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html.jinja"), 404


# ---------------- Auto Delete Cancelled Appointments----------------
def cleanup_cancelled_appointments():
    print("Cleaning up old cancelled appointments...")

    connection = connect_db()
    cursor = connection.cursor()

    cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=1)

    cursor.execute("""
        DELETE FROM Appointment
        WHERE Status = 'Cancelled'
        AND Date < %s
    """, (cutoff_time,))

    connection.commit()
    connection.close()

## ---------------- SEND EMAIL REMINDER ----------------
# ---------------- EMAIL REMINDERS ----------------
def send_reminder(email, doctor_name, appointment_time, patient_name):
    with app.app_context(): 
        msg = Message(
            subject="BookWell Appointment Reminder",
            recipients=[email],
        )
        msg.body = f"""
Dear {patient_name},

This is a friendly reminder regarding your upcoming medical appointment scheduled through BookWell. Please find the details of your appointment below:

Doctor: Dr. {doctor_name}
Date: {appointment_time.strftime('%Y-%m-%d')}
Time: {appointment_time.strftime('%H:%M')}

We kindly ask that you arrive a few minutes early to allow time for check-in and any necessary paperwork.

If you are unable to attend or need to reschedule your appointment, please log in to your BookWell account at your earliest convenience to make the necessary changes. Providing advance notice helps us offer the appointment time to other patients who may be waiting.

If you have any questions or require assistance, please do not hesitate to contact our support team.

Thank you for choosing BookWell for your healthcare scheduling needs. We look forward to serving you.

Warm regards,  
The BookWell Team
"""
        try:
            mail.send(msg)
            print("Reminder sent successfully.")
        except Exception as e:
            print(f"Failed to send reminder: {e}")


# ---------------- CHECK APPOINTMENT REMINDERS ----------------
def check_appointment_reminders():
    print("Checking for upcoming appointments to remind...")
    connection = connect_db()
    cursor = connection.cursor()

    now = datetime.datetime.now()
    reminder_window = now + datetime.timedelta(minutes=20)  # For testing: 1 min ahead

    cursor.execute("""
        SELECT Appointment.ID, Appointment.Date,
               User.Email AS user_email,
               User.Name AS user_name,
               Doctor.Name AS doctor_name
        FROM Appointment
        JOIN User ON User.ID = Appointment.UserID
        JOIN Doctor ON Doctor.ID = Appointment.DoctorID
        WHERE Appointment.Status='Scheduled'
        AND Appointment.Date BETWEEN %s AND %s
    """, (now, reminder_window))

    appointments = cursor.fetchall()
    connection.close()

    for appt in appointments:
        send_reminder(
            appt["user_email"],    # client email
            appt["doctor_name"],   # doctor name
            appt["Date"],          # appointment datetime
            appt["user_name"]      # client name
        )


# ---------------- CONFIRMATION EMAIL ----------------------
def send_confirmation_email(email, doctor_name, appointment_time, patient_name, visit_type):
    with app.app_context():
        msg = Message(
            subject="BookWell Appointment Confirmation",
            recipients=[email],
        )

        msg.body = f"""
Dear {patient_name},

Your appointment has been successfully scheduled with BookWell. Please find your appointment details below:

Doctor: Dr. {doctor_name}
Date: {appointment_time.strftime('%Y-%m-%d')}
Time: {appointment_time.strftime('%H:%M')}
Visit Type: {visit_type}

We recommend arriving at least 5–10 minutes early to ensure a smooth check-in process.

If you need to reschedule or cancel your appointment, you can do so by logging into your BookWell account.

If you have any questions or need assistance, feel free to contact our support team.

Thank you for choosing BookWell for your healthcare needs.

Warm regards,  
The BookWell Team
"""
        try:
            mail.send(msg)
            print("Confirmation email sent successfully.")
        except Exception as e:
            print(f"Failed to send confirmation email: {e}")




# ---------------- START REMINDER SCHEDULER ----------------
scheduler = BackgroundScheduler()
scheduler.add_job(check_appointment_reminders, "interval", minutes=15)
scheduler.add_job(cleanup_cancelled_appointments, "interval", seconds=30)
scheduler.start()


@app.route("/aboutus")
def about():
    return render_template("aboutus.html.jinja")