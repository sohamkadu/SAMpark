import qrcode
import secrets
import os
import requests

from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()
print("Edesy API key loaded:", bool(os.getenv("EDESY_API_KEY")))

app.secret_key = "sampark-development-secret-key"

# Database configuration
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///sampark.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# User table
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password = db.Column(db.String(255), nullable=False)

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    vehicle_name = db.Column(db.String(100), nullable=False)

    registration_number = db.Column(db.String(50), nullable=False, unique=True)

    qr_token = db.Column(db.String(100), unique=True, nullable=False)

    active = db.Column(db.Boolean, default=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


# Create database
with app.app_context():
    db.create_all()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        email = request.form["email"]
        phone = request.form["phone"]
        password = request.form["password"]

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            return "Email Already Registered"

        if not phone.isdigit() or len(phone) != 10:
            return "Please enter a valid 10-digit phone number.", 400

        hashed_password = generate_password_hash(password)

        new_user = User(
            email=email,
            phone=phone,
            password=hashed_password
        )

        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for("home"))

    return render_template("register.html")


@app.route("/login", methods=["GET","POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):

            session["user_id"] = user.id

            return redirect(url_for("dashboard"))

    return render_template("login.html")

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])

    vehicles = Vehicle.query.filter_by(user_id=session["user_id"]).all()

    return render_template("dashboard.html", user=user, vehicles=vehicles)

@app.route("/vehicle/add", methods=["GET", "POST"])
def add_vehicle():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        vehicle_name = request.form["vehicle_name"]
        registration_number = request.form["registration_number"]
        registration_number = registration_number.upper()

        # Generate a unique token
        qr_token = secrets.token_urlsafe(16)

        new_vehicle = Vehicle(
            vehicle_name=vehicle_name,
            registration_number=registration_number,
            qr_token=qr_token,
            user_id=session["user_id"]
        )

        db.session.add(new_vehicle)
        db.session.commit()

        return redirect(url_for("dashboard"))

    return render_template("add_vehicle.html")


@app.route('/logout')
def logout():
    session.clear()

    return redirect(url_for('login'))

@app.route("/vehicle/<int:vehicle_id>/qr")
def vehicle_qr(vehicle_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    vehicle = Vehicle.query.filter_by(
        id=vehicle_id,
        user_id=session["user_id"]
    ).first_or_404()

    # URL that the QR code will contain
    contact_url = url_for(
        "contact_vehicle",
        qr_token=vehicle.qr_token,
        _external=True
    )

    return render_template(
        "vehicle_qr.html",
        vehicle=vehicle,
        contact_url=contact_url
    )

@app.route("/contact/<qr_token>")
def contact_vehicle(qr_token):

    vehicle = Vehicle.query.filter_by(
        qr_token=qr_token
    ).first_or_404()

    return render_template(
        "contact.html",
        vehicle=vehicle
    )

@app.route("/call/<qr_token>", methods=["POST"])
def call_owner(qr_token):

    # Get caller's phone number
    caller_phone = request.form.get("caller_phone", "").strip()

    # Check phone number
    if not caller_phone.isdigit() or len(caller_phone) != 10:
        return "Please enter a valid 10-digit Indian mobile number.", 400

    # Find vehicle
    vehicle = Vehicle.query.filter_by(
        qr_token=qr_token
    ).first_or_404()

    # Find owner
    owner = User.query.get(vehicle.user_id)

    if not owner:
        return "Vehicle owner not found.", 404

    # Check owner's phone
    if not owner.phone.isdigit() or len(owner.phone) != 10:
        return "Owner phone number is invalid.", 500

    # Get Edesy API key
    edesy_api_key = os.getenv("EDESY_API_KEY")

    if not edesy_api_key:
        return "Edesy API key is not configured.", 500

    # Edesy API
    url = "https://voice-api.edesy.in/v1/masking/calls"

    headers = {
        "Authorization": f"Bearer {edesy_api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "party_a": caller_phone,
        "party_b": owner.phone
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=data,
            timeout=15
        )

    except requests.RequestException as e:

        print("Edesy connection error:", e)

        return "Unable to connect to calling service.", 500

    print("Edesy status:", response.status_code)
    print("Edesy response:", response.text)

    if response.status_code == 201:

        result = response.json()

        return render_template(
            "call_requested.html",
            vehicle=vehicle,
            call_sid=result["data"]["call_sid"]
        )

    return f"""
        <h1>Unable to start call</h1>
        <p>{response.text}</p>
    """, response.status_code



if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )