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

    cursor.execute("SELECT * `Doctor` WHERE `ID` = %s", (Doctor_id))

    result = cursor.fetchone()

    cursor.execute("SELECT * FROM `Review` JOIN `User` ON `User`. `ID` = `Review` . `userID` `DoctorID` = %s", (Doctor_id))

    result2 = cursor.fetchall()

    connection.close()

    if result is None:
        abort(404)

    return render_template("doctor.html.jinja", doctor = result, review = result2)




@app.route("/doctor/<Doctor_id>/review", methods=["POST"])
@login_required
def Review1(Doctor_id):

    rating = request.form["Rating"]

    comment = request.form["comments"]

    connection = connect_db()
    
    cursor = connection.cursor()

    cursor.execute("""
    INSERT INTO `Review` (`UserID`, `Comments`, `Rating`, `DoctorID`)
    VALUES (%s, %s, %s, %s)
                   
    """,(current_user.id, comment, rating, Doctor_id))

    return redirect(f"/doctor/{Doctor_id}")
    




@app.route("/appoint")
@login_required
def appoint():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("""
    SELECT * FROM `Appointment`
    JOIN `Doctor` ON `Doctor`. `ID` = `Appointment`. `DoctorID`
    WHERE `UserID` = %s
    """, (current_user.id))
    result = cursor.fetchall()

    connection.close()
    return render_template("appoint.html.jinja", appointment = result)




@app.route("/doctorsearch")
def doctorsearch():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `Doctor` ")

    result = cursor.fetchall()

    connection.close()
    return render_template("doctorsearch.html.jinja", doctors = result)







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






     







