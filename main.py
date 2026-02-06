from flask import Flask, render_template, request, flash, redirect, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import pymysql

from dynaconf import Dynaconf

app = Flask(__name__)

config = Dynaconf(settings_file=["settings.toml"])

app.secret_key = config.SECRET_KEY

login_manager = LoginManager(app)

@app.route("/")
def index():
    return render_template("homepage.html.jinja")