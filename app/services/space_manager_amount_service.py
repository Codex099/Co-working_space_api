from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from models.domain import User, Booking, SpaceManagerEarning, Settlement

def calculate_and_save_manager_earning(db: Session, booking_id: int, manager_id: str):
    # ... (rest of the existing function)
    manager = db.query(User).filter(User.id == manager_id).first()
    if not manager:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")

    if manager.role != "space_manager":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Impossible de créer des revenus : cet utilisateur n'est pas un Manager d'Espace."
        )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réservation introuvable")

    if not booking.total_price:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le prix de la réservation n'est pas défini")

    # Commission rate might be dynamic per location in the future, currently hardcoded or taken from location if available
    commission_rate = 0.15 
    if booking.room and booking.room.location:
        commission_rate = booking.room.location.commission_rate or 0.15
    
    gross_p = booking.total_price
    commission_p = gross_p * commission_rate
    net_p = gross_p - commission_p

    new_earning = SpaceManagerEarning(
        booking_id=booking.id,
        manager_id=manager.id,
        gross_amount=gross_p,
        commission_amount=commission_p,
        net_amount=net_p
    )

    db.add(new_earning)
    db.commit()
    db.refresh(new_earning)
    return new_earning

def get_manager_pending_balance(db: Session, manager_id: str):
    """Calculates the total pending (unpaid) net amount for a manager."""
    total_net = db.query(func.sum(SpaceManagerEarning.net_amount))\
        .filter(SpaceManagerEarning.manager_id == manager_id, SpaceManagerEarning.settlement_id == None)\
        .scalar() or 0.0
    return round(total_net, 2)

def create_settlement(db: Session, manager_id: str, amount_paid: float, notes: str = None):
    """Marks earnings as settled and records the payment."""
    # 0. Check if amount_paid is valid
    pending_balance = get_manager_pending_balance(db, manager_id)
    if amount_paid > pending_balance + 0.01:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Le montant versé ({amount_paid} DA) est supérieur au solde en attente ({pending_balance} DA)."
        )

    # 1. Get unpaid earnings
    unpaid = db.query(SpaceManagerEarning).filter(
        SpaceManagerEarning.manager_id == manager_id,
        SpaceManagerEarning.settlement_id == None
    ).order_by(SpaceManagerEarning.created_at.asc()).all()

    # 2. Link earnings to this settlement up to amount_paid
    covered_earnings = []
    current_sum = 0
    total_comm_cleared = 0
    
    for e in unpaid:
        if current_sum + e.net_amount <= amount_paid + 0.1: # tiny buffer
            covered_earnings.append(e)
            current_sum += e.net_amount
            total_comm_cleared += e.commission_amount
        else:
            break

    # 3. Create the record
    new_settlement = Settlement(
        manager_id=manager_id,
        amount_paid=amount_paid,
        total_commission=total_comm_cleared,
        notes=notes
    )
    db.add(new_settlement)
    db.flush() # Get ID without full commit yet

    for e in covered_earnings:
        e.settlement_id = new_settlement.id
    
    db.commit()
    db.refresh(new_settlement)
    return new_settlement

def get_settlement_history(db: Session, manager_id: str = None):
    """Returns the list of settlements."""
    query = db.query(Settlement).order_by(Settlement.created_at.desc())
    if manager_id:
        query = query.filter(Settlement.manager_id == manager_id)
    return query.all()

def delete_settlement(db: Session, settlement_id: int):
    """Deletes a settlement and releases associated earnings."""
    settlement = db.query(Settlement).filter(Settlement.id == settlement_id).first()
    if not settlement:
        raise HTTPException(status_code=404, detail="Règlement introuvable")
    
    # 1. Reset settlement_id in earnings
    db.query(SpaceManagerEarning).filter(SpaceManagerEarning.settlement_id == settlement_id).update({SpaceManagerEarning.settlement_id: None})
    
    # 2. Delete settlement
    db.delete(settlement)
    db.commit()
    return True
