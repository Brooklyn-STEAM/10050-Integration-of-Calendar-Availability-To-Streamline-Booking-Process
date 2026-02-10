from flask import Flask, render_template, request, flash, redirect
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import pymysql

from dynaconf import Dynaconf

app = Flask(__name__)

config = Dynaconf(settings_file=["settings.toml"])

app.secret_key = config.secret_key


@app.route("/")
def index():
    return render_template("homepage.html.jinja")

@app.route("/docor.html.jinja")
def search():
    connection = connect_db()

    cursor = connection.cursor

    cursor.execute("SELECT * FROM `Doctor`")

    connection.close()
    return render_template("docor.html.jinja")
