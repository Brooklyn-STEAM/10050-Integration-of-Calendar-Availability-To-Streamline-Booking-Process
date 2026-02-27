from flask import Flask, render_template, request, flash, redirect, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import pymysql

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

    return redirect("/thank-you")

@app.route("/doctor/<Doctor_id>/book", methods=["POST"])
@login_required
def book_appointment(Doctor_id):

    date = request.form.get("date")
    time = request.form.get("time")
    visit_type = request.form.get("visit_type")

    type_field = f"{visit_type} {time}"

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO `Appointment` (`DoctorID`, `UserID`, `Date`, `Type`, `Status`)
        VALUES (%s, %s, %s, %s, %s)
    """, (Doctor_id, current_user.id, date, type_field, "Scheduled"))

    connection.close()

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

@app.route("/thank-you")
def thank():
    return render_template("thank-you.html.jinja")






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






     







