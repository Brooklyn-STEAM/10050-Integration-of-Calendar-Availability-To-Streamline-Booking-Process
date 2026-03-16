from flask import Flask, render_template, request, flash, redirect, abort, url_for
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import pymysql
import datetime 
import os
import calendar as cal
from dynaconf import Dynaconf

app = Flask(__name__)

config = Dynaconf(settings_file=["settings.toml"])

app.secret_key = config.secret_key

login_manager = LoginManager(app)

login_manager.login_view = '/login'

class User:
    is_authenticated = True
    is_active = True
    is_annoymous = False 

    def __init__(self, result):
        self.name = result['Name']
        self.email = result['Email']
        self.address = result['Address']
        self.join = result['Joindate']
        self.id = result['ID']

    def get_id(self):
        return str(self.id)
    
@login_manager.user_loader
def load_user(user_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM User WHERE ID = %s", (user_id) )
    result = cursor.fetchone()
    connection.close()

    if result is None:
        return None
    
    return User(result)
    



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



@app.route("/")
def index():
    return render_template("homepage.html.jinja")

@app.route("/doctor")
def doctor():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `Doctor` ")

    result = cursor.fetchall()

    connection.close()
    return render_template("doctor.html.jinja", doctors = result )

@app.route("/doctor/<Doctor_id>")
def doctor_page(Doctor_id):
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `Doctor` WHERE `ID` = %s", (Doctor_id,))

    result = cursor.fetchone()

    cursor.execute("SELECT * FROM `Review` JOIN `User` ON `User`.`ID` = `Review`.`userID` WHERE `Review`.`DoctorID` = %s", (Doctor_id,))

    result2 = cursor.fetchall()

    connection.close()

    if result is None:
        abort(404) 

    return render_template("doctor.html.jinja", doctor = result, reviews=result2)

    
@app.route("/appoint")
@login_required
def appoint():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("""
    SELECT Appointment.ID, Appointment.Date, Appointment.Type, Appointment.Status, Doctor.Name AS DoctorName, Doctor.Location AS Location 
    FROM `Appointment`
    JOIN `Doctor` ON `Doctor`.`ID` = `Appointment`.`DoctorID`
    WHERE `UserID` = %s
    """, (current_user.id,))
    appointments = cursor.fetchall()

    connection.close()
    return render_template("appoint.html.jinja", appointments = appointments)

@app.route("/appointments")
def appointments():
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `Appointment`")
    appointments = cursor.fetchall()

    connection.close()
    return render_template("appoint.html.jinja", appointments=appointments)

@app.route("/doctor/<Doctor_id>/review", methods=["POST"])
@login_required
def submit_review(Doctor_id):

    rating = request.form["rating"]
    comment = request.form["comments"]

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO `Review` (`UserID`, `Comments`, `Rating`, `DoctorID`)
        VALUES (%s, %s, %s, %s)
    """, (current_user.id, comment, rating, Doctor_id))

    connection.close()

    return redirect(f"/doctor/{Doctor_id}")

@app.route("/doctor/<Doctor_id>/book", methods=["POST"])
@login_required
def book_appointment(Doctor_id):

    date = request.form.get("date")
    time = request.form.get("time")
    visit_type = request.form.get("visit_type")

    start_datetime = f"{date} {time}"

    connection = connect_db()
    cursor = connection.cursor()

    # 1️⃣ Check if doctor has this slot available
    cursor.execute("""
        SELECT * FROM DoctorAvailability
        WHERE DoctorID = %s
        AND AvailableDate = %s
        AND Booked = 0
    """, (Doctor_id, start_datetime))

    available_slot = cursor.fetchone()

    if not available_slot:
        connection.close()
        flash("This time slot is not available.", "error")
        return redirect(f"/doctor/{Doctor_id}")


    type_field = f"{visit_type} {time}"

    cursor.execute("""
        INSERT INTO Appointment (DoctorID, UserID, Date, Type, Status)
        VALUES (%s, %s, %s, %s, %s)
    """, (Doctor_id, current_user.id, start_datetime, type_field, "Scheduled"))


    cursor.execute("""
        UPDATE DoctorAvailability
        SET Booked = 1
        WHERE DoctorID = %s
        AND AvailableDate = %s
    """, (Doctor_id, start_datetime))

    connection.close()

    flash("Appointment successfully booked!", "success")
    return redirect("/thanks")

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








@app.route("/doctorsearch", methods=["GET"])
def doctorsearch():
    search_query = request.args.get("q", "")  # get search input
    category_filter = request.args.get("category", "")  # get category filter

    connection = connect_db()
    cursor = connection.cursor()

    sql = "SELECT * FROM `Doctor` WHERE 1=1"
    params = []

    if search_query:
        sql += " AND `Name` LIKE %s"
        params.append(f"%{search_query}%")
    
    if category_filter:
        sql += " AND `Category` = %s"
        params.append(category_filter)

    cursor.execute(sql, params)
    doctors = cursor.fetchall()
    connection.close()

    return render_template("doctorsearch.html.jinja", doctors=doctors, search_query=search_query, category_filter=category_filter) 




@app.route('/calendar')
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

    # Organize appointments by date
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


@app.route("/login", methods=["POST", "GET"])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        connection = connect_db()

        cursor = connection.cursor()

        cursor.execute("SELECT * FROM `User` WHERE `Email` = %s", (email))

        result = cursor.fetchone()

        connection.close()

        if result is None:
                flash("No account found.")

        elif password != result ['Password']:
                flash("Wrong Password!")

        else:
            login_user (User(result))

            return redirect ("/")

    return render_template("login.html.jinja")


    

@app.route("/signup", methods=["POST","GET"])
def signup():
    if request.method =='POST':
        name= request.form["name"]
        email = request.form["email"]

        password = request.form['password']
        confirm_password = request.form["confirm_password"]
        address = request.form["address"]

        if password != confirm_password:
            flash("Passwords do not match")
        elif len(password) < 8:
            flash("Password is too short")
        else:
            connection = connect_db()

            cursor = connection.cursor ()
            try:
                cursor.execute("""
                    INSERT INTO `User` (`Name`, `Password`, `Email`, `Address`)
                    VALUES (%s, %s, %s, %s)
                """, (name, password, email, address) )
                connection.close()
            except pymysql.err.IntegrityError:
                flash("User with that email already exists")

            else:
                 return redirect('/login')
            
    return render_template("signup.html.jinja")

@app.route("/logout", methods=["POST", "GET"])
@login_required
def logout():
    logout_user()    
    return redirect("/")


@app.route("/thanks")
def thanks():
    return render_template("thanks.html.jinja")


@app.route("/thankscontact")
def thankscontact():
    return render_template("thankscontact.html.jinja")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        message = request.form.get("message")

        
        if not name or not email or not message:
            flash("Please fill in all fields.", "error")
            return redirect("/contact")

        
        print(f"New message from {name} ({email}): {message}")

        flash("Your message has been sent successfully!", "success")
        return redirect("/thankscontact")

    return render_template("contactus.html.jinja")

@app.route("/doctorlogin", methods=["GET","POST"])
def doctor_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        connection = connect_db()
        cursor = connection.cursor()

        cursor.execute("SELECT * FROM Doctor WHERE Email = %s", (email,))
        doctor = cursor.fetchone()

        connection.close()

        if doctor is None:
            flash("Doctor account not found.")
        elif password != doctor["Password"]:
            flash("Incorrect password.")
        else:
            flash("Doctor login successful.")
            return redirect(f"/doctor/{doctor['ID']}/homepage")

    return render_template("doctorlogin.html.jinja")
@app.route("/doctor/<int:doctor_id>/homepage")
def doctor_dashboard(doctor_id):

    connection = connect_db()
    cursor = connection.cursor()


    cursor.execute("SELECT * FROM Doctor WHERE ID = %s", (doctor_id,))
    doctor = cursor.fetchone()

    if doctor is None:
        connection.close()
        abort(404)

  
    cursor.execute("""
        SELECT Appointment.ID, Appointment.Date, Appointment.Type, Appointment.Status,
        User.Name AS PatientName
        FROM Appointment
        JOIN User ON User.ID = Appointment.UserID
        WHERE Appointment.DoctorID = %s
        ORDER BY Appointment.Date
    """, (doctor_id,))

    appointments = cursor.fetchall()

    connection.close()

    return render_template("doctorhomepage.html.jinja", doctor=doctor, appointments=appointments)

@app.route("/doctor/<int:doctor_id>/appointments", methods=["GET", "POST"])
def doctor_appointments(doctor_id):
    connection = connect_db()
    cursor = connection.cursor()

    # Fetch doctor info
    cursor.execute("SELECT * FROM Doctor WHERE ID = %s", (doctor_id,))
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
                SET Status = 'Cancelled'
                WHERE ID = %s AND DoctorID = %s
            """, (appointment_id, doctor_id))
            flash("Appointment cancelled successfully.", "success")

        elif action == "reschedule":
            new_date = request.form.get("new_date")
            new_time = request.form.get("new_time")
            if new_date and new_time:
                new_datetime = f"{new_date} {new_time}"
                cursor.execute("""
                    UPDATE Appointment
                    SET Date = %s, Status = 'Scheduled'
                    WHERE ID = %s AND DoctorID = %s
                """, (new_datetime, appointment_id, doctor_id))
                flash("Appointment rescheduled successfully.", "success")
        connection.commit()


    cursor.execute("""
        SELECT Appointment.ID, Appointment.Date, Appointment.Type, Appointment.Status,
               User.Name AS PatientName
        FROM Appointment
        JOIN User ON User.ID = Appointment.UserID
        WHERE Appointment.DoctorID = %s
        ORDER BY Appointment.Date
    """, (doctor_id,))
    appointments = cursor.fetchall()
    connection.close()

    return render_template(
        "doctorappoint.html.jinja",
        appointments=appointments,
        doctor=doctor
    )


@app.route('/aboutus')
def about():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `AboutUs` ")

    result = cursor.fetchall()

    connection.close()
    
    return render_template("aboutus.html.jinja", about = result)