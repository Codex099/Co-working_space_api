from models.domain import User
from db.database import db
import bcrypt
import random

# For storing temporarily
signup_codes = {}
pending_users = {}

# Hash the plain password before saving to the database.
# bcrypt.hashpw() generates a salted hash suitable for secure storage.
def hash_password(plain_password):
    # Generate salt and hash password
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(str(plain_password).encode('utf-8'), salt).decode('utf-8')

# Verify a login password against the stored hashed password.
def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(str(plain_password).encode('utf-8'), hashed_password.encode('utf-8'))


def get_user_by_email(email):
    return User.query.filter_by(email=email).first()

def get_user_by_number(number):
    return User.query.filter_by(number=number).first()

def get_user_by_id(user_id):
    return User.query.get(user_id)

def get_user_balance(user_id):
    user = get_user_by_id(user_id)
    if not user:
        return 0.0
    return user.balance

def create_user_db(data):
    # Hash the password once, then store the hash instead of plain text.
    hashed_password = hash_password(data['password'])

    user = User(
        name=data['name'],
        email=data['email'],
        number=data['number'],
        password=hashed_password,
        role=data.get('role', 'Normal user'),
        balance=data.get('balance', 0.0)
    )
    db.session.add(user)
    db.session.commit()
    return user

def save_user(user):
    db.session.commit()

def delete_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return False
    db.session.delete(user)
    db.session.commit()
    return True

def get_all_users():
    return User.query.all()

def create_user(data):
    if not data or not all(k in data for k in ("name", "email", "password", "number",)):
        return {"error": "Missing data"}, 400
    if not data['email'] or not data['number']:
        return {"error": "Email or number cannot be null"}, 400
    if get_user_by_email(data['email']):
        return {"error": "Email already exists"}, 400
    if get_user_by_number(data['number']):
        return {"error": "Number already exists"}, 400
    user = create_user_db(data)
    return {"message": "User created", "user_id": user.id}, 201

def get_user_by_email_logic(email):
    user = get_user_by_email(email)
    if not user:
        return {"error": "User not found"}, 404
    balance = get_user_balance(user.id)
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "balance": balance,
        "number": user.number
    }, 200

def login_user(data):
    if not data or not all(k in data for k in ("email", "password")):
        return {"error": "Missing data"}, 400

    user = get_user_by_email(data['email'])
    # Verify the clear text password against the bcrypt hash stored in DB.
    if not user or not verify_password(data['password'], user.password):
        return {"error": "Invalid credentials"}, 401

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "balance": user.balance
    }, 200

def signup_request(data):
    if not data or not all(k in data for k in ("name", "email", "password", "number")):
        return {"error": "Missing data"}, 400
    if not data['email'] or not data['number']:
        return {"error": "Email or number cannot be null"}, 400
    if get_user_by_email(data['email']):
        return {"error": "Email already exists"}, 400

    # Store the sign-up request temporarily until confirmation.
    # The password is not stored in the DB until the code is confirmed.
    code = str(random.randint(10000, 99999))
    signup_codes[data['email']] = code
    pending_users[data['email']] = data

    print(f"Code de confirmation pour {data['email']} : {code}")

    return {"message": "Confirmation code sent (see terminal)", "email": data['email']}, 200

def confirm_signup(email, code):
    expected_code = signup_codes.get(email)
    if not expected_code:
        return {"error": "No code found for this email"}, 400
    if code != expected_code:
        return {"error": "Invalid code"}, 401

    user = create_user_db(pending_users[email])

    del signup_codes[email]
    del pending_users[email]

    return {"message": "User created", "user_id": user.id}, 201

def get_user_by_id_logic(user_id):
    user = get_user_by_id(user_id)
    if not user:
        return {"error": "User not found"}, 404
    balance = get_user_balance(user.id)
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "balance": balance,
        "number": user.number
    }, 200

def update_user_by_id(user_id, data):
    user = get_user_by_id(user_id)
    if not user:
        return {"error": "User not found"}, 404
    user.name = data.get('name', user.name)
    user.email = data.get('email', user.email)
    user.number = data.get('number', user.number)
    save_user(user)
    return {"message": "User updated"}, 200
