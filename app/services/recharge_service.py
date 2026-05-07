from models.domain import Recharge
from db.database import db
from datetime import datetime
from services.user_service import get_user_by_uid, save_user

def create_recharge_db(data):
    user = get_user_by_uid(data['user_id'])
    if not user:
        return None
    recharge = Recharge(user_id=user.firebase_uid, amount=data['amount'], date=datetime.utcnow())
    db.session.add(recharge)
    user.balance += data['amount']
    db.session.add(user)
    db.session.commit()
    return recharge

def get_user_recharges(user_uid):
    return Recharge.query.filter_by(user_id=user_uid).order_by(Recharge.date.desc()).all()

def create_recharge(data):
    user = get_user_by_uid(data['user_id'])
    if not user:
        return {"error": "User not found"}, 404

    recharge = create_recharge_db(data)

    return {"message": "Recharge successful", "new_balance": user.balance}, 201

def get_all_recharges():
    return Recharge.query.all()
