from flask import Flask, render_template, request, flash, redirect
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

@app.route("/docor")
def docor():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `DoctorAvailability` ")

    result = cursor.fetchall()

    connection.close()
    return render_template("docor.html.jinja")

@app.route("/appoint")
def appoint():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `Appointment` ")

    result = cursor.fetchall()

    connection.close()
    return render_template("appoint.html.jinja")

@app.route("/doctorsearch")
def doctorsearch():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `Doctor` ")

    result = cursor.fetchall()

    connection.close()
    return render_template("doctorsearch.html.jinja")







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


    return render_template("doctorsearch.html.jinja")







