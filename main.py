from flask import Flask, render_template, request, flash, redirect, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import pymysql
import datetime
import calendar as cal
from dynaconf import Dynaconf

from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler

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
@app.route("/doctor")
def doctor():
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM Doctor")
    result = cursor.fetchall()

    connection.close()

    return render_template("doctor.html.jinja", doctors=result)


@app.route("/doctor/<Doctor_id>")
def doctor_page(Doctor_id):

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM Doctor WHERE ID = %s", (Doctor_id,))
    doctor = cursor.fetchone()

    if doctor is None:
        connection.close()
        abort(404)

    cursor.execute("""
        SELECT * FROM Review
        JOIN User ON User.ID = Review.UserID
        WHERE Review.DoctorID = %s
    """, (Doctor_id,))
    reviews = cursor.fetchall()

    cursor.execute("""
        SELECT DATE(AvailableDate) AS blocked_date
        FROM DoctorAvailability
        WHERE DoctorID = %s AND Booked = 1
    """, (Doctor_id,))
    blocked_dates = [
        row["blocked_date"].strftime("%Y-%m-%d")
        for row in cursor.fetchall()
    ]

    connection.close()

    return render_template(
        "doctor.html.jinja",
        doctor=doctor,
        reviews=reviews,
        blocked_dates=blocked_dates
    )


# ---------------- APPOINTMENTS ----------------
@app.route("/appoint")
@login_required
def appoint():

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT Appointment.ID, Appointment.Date, Appointment.Type, Appointment.Status,
               Doctor.Name AS DoctorName, Doctor.Location AS Location
        FROM Appointment
        JOIN Doctor ON Doctor.ID = Appointment.DoctorID
        WHERE UserID = %s
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


# ---------------- BOOK APPOINTMENT ----------------
@app.route("/doctorsearch", methods=["GET"])
def doctorsearch():

    search_query = request.args.get("q", "")
    category_filter = request.args.get("category", "")

    connection = connect_db()
    cursor = connection.cursor()

    sql = "SELECT * FROM Doctor WHERE 1=1"
    params = []

    if search_query:
        sql += " AND Name LIKE %s"
        params.append(f"%{search_query}%")

    if category_filter:
        sql += " AND Category = %s"
        params.append(category_filter)

    cursor.execute(sql, params)
    doctors = cursor.fetchall()

    connection.close()

    return render_template(
        "doctorsearch.html.jinja",
        doctors=doctors,
        search_query=search_query,
        category_filter=category_filter
    )


@app.route("/calendar")
@login_required
def calendar_view():

    connection = connect_db()
    cursor = connection.cursor()

    today = datetime.date.today()
    year = today.year
    month = today.month

    cursor.execute("""
        SELECT ID, Date, Type, Status
        FROM Appointment
        WHERE UserID = %s
        AND MONTH(Date) = %s
        AND YEAR(Date) = %s
    """, (current_user.id, month, year))

    appointments = cursor.fetchall()
    connection.close()

    events = {}

    for appt in appointments:
        date_key = appt["Date"].strftime("%Y-%m-%d")

        if date_key not in events:
            events[date_key] = []

        events[date_key].append(appt)

    month_calendar = cal.monthcalendar(year, month)
    month_name = cal.month_name[month]

    return render_template(
        "calendar.html.jinja",
        calendar=month_calendar,
        events=events,
        year=year,
        month=month,
        month_name=month_name,
        today=today.strftime("%Y-%m-%d")
    )


@app.route("/doctor/<Doctor_id>/book", methods=["POST"])
@login_required
def book_appointment(Doctor_id):

    date = request.form.get("date")
    time = request.form.get("time")
    visit_type = request.form.get("visit_type")

    if not date or not time or not visit_type:
        flash("Please provide date, time, and visit type.")
        return redirect(f"/doctor/{Doctor_id}")

    start_datetime = datetime.datetime.strptime(
        f"{date} {time}", "%Y-%m-%d %H:%M"
    )
    end_datetime = start_datetime + datetime.timedelta(minutes=20)

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT * FROM Appointment
        WHERE DoctorID = %s
        AND Status != 'Cancelled'
        AND Date >= %s
        AND Date < %s
    """, (Doctor_id, start_datetime, end_datetime))

    existing = cursor.fetchone()

    if existing:
        connection.close()
        flash("Doctor not available at this time.")
        return redirect(f"/doctor/{Doctor_id}")

    cursor.execute("""
        SELECT * FROM DoctorAvailability
        WHERE DoctorID = %s
        AND DATE(AvailableDate) = %s
        AND Booked = 1
    """, (Doctor_id, date))

    blocked = cursor.fetchone()

    if blocked:
        connection.close()
        flash("Doctor unavailable on this date.")
        return redirect(f"/doctor/{Doctor_id}")

    cursor.execute("""
        INSERT INTO Appointment (DoctorID, UserID, Date, Type, Status)
        VALUES (%s, %s, %s, %s, %s)
    """, (Doctor_id, current_user.id, start_datetime, visit_type, "Scheduled"))

    connection.commit()
    connection.close()

    flash("Appointment successfully booked!")
    return redirect("/appoint")

@app.route("/appoint/<int:appointment_id>/cancel", methods=["POST"])
@login_required
def cancel_appointment(appointment_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("""
        UPDATE `Appointment`
        SET `Status` = 'Cancelled'
        WHERE `ID` = %s AND `UserID` = %s
    """, (appointment_id, current_user.id))

    connection.close()
    flash("Appointment has been cancelled.")
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
            flash("No account found")

        elif password != result["Password"]:
            flash("Wrong password")

        else:
            login_user(User(result))
            return redirect("/")

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
def doctor_login():

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

        elif action == "reschedule":

            new_date = request.form.get("new_date")
            new_time = request.form.get("new_time")

            if new_date and new_time:

                new_datetime = f"{new_date} {new_time}"

                cursor.execute("""
                    UPDATE Appointment
                    SET Date=%s, Status='Scheduled'
                    WHERE ID=%s AND DoctorID=%s
                """, (new_datetime, appointment_id, doctor_id))

                flash("Appointment rescheduled")

        connection.commit()

    cursor.execute("""
        SELECT Appointment.ID, Appointment.Date, Appointment.Type, Appointment.Status,
               User.Name AS PatientName
        FROM Appointment
        JOIN User ON User.ID = Appointment.UserID
        WHERE Appointment.DoctorID=%s
        ORDER BY Appointment.Date
    """, (doctor_id,))

    appointments = cursor.fetchall()

    connection.close()

    return render_template(
        "doctorappoint.html.jinja",
        doctor=doctor,
        appointments=appointments
    )


@app.route("/doctor/<int:doctor_id>/calendar")
def doctor_calendar(doctor_id):

    today = datetime.date.today()
    year = today.year
    month = today.month

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM Doctor WHERE ID=%s", (doctor_id,))
    doctor = cursor.fetchone()

    cursor.execute("""
        SELECT Date,Type,Status
        FROM Appointment
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
        key = appt["Date"].strftime("%Y-%m-%d")
        events.setdefault(key, []).append(appt)

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
        month=month
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







# ---------------- START REMINDER SCHEDULER ----------------
scheduler = BackgroundScheduler()
scheduler.add_job(check_appointment_reminders, "interval", minutes=5)
scheduler.start()


# ---------------- RUN APP ----------------
if __name__ == "__main__":
    app.run(debug=True)