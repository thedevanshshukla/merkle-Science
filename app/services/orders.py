"""Order operations: placing, paying and cancelling purchases."""
from datetime import datetime
from typing import Dict

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Book, Member, MemberTier, Order, OrderItem, OrderStatus
from app.services.members import ensure_can_access_restricted
from app.schemas import OrderCreate

# Percentage discount granted by each membership tier.
TIER_DISCOUNT_PERCENT: Dict[str, int] = {
    MemberTier.APPRENTICE.value: 0,
    MemberTier.ADEPT.value: 5,
    MemberTier.MASTER.value: 10,
    MemberTier.SUPREME.value: 15,
}

# Extra discount when the total quantity across all items reaches the threshold.
BULK_QUANTITY_THRESHOLD = 10
BULK_DISCOUNT_PERCENT = 5


def calculate_discount_percent(member: Member, total_quantity: int) -> int:
    """Return the member tier discount plus any bulk discount."""

    discount_percent = TIER_DISCOUNT_PERCENT[member.tier]

    if total_quantity >= BULK_QUANTITY_THRESHOLD:
        discount_percent += BULK_DISCOUNT_PERCENT

    return discount_percent


def create_order(db: Session, data: OrderCreate, now: datetime) -> Order:
    """Place a pending order and reserve stock."""

    member = db.get(Member, data.member_id)

    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    # Lock existing books in a stable ID order. PostgreSQL holds these row locks
    # until commit, so concurrent orders re-check stock after earlier orders finish.
    book_ids = [item.book_id for item in data.items]
    books_by_id = {
        book.id: book
        for book in db.scalars(
            select(Book)
            .where(Book.id.in_(book_ids))
            .order_by(Book.id)
            .with_for_update()
        )
    }

    books = []
    for item in data.items:
        book = books_by_id.get(item.book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="Book not found")
        books.append(book)

    # Restricted access must be checked before stock availability.
    for book in books:
        if book.restricted:
            ensure_can_access_restricted(member)

    # Check all stock before changing any stock.
    for item, book in zip(data.items, books):
        if book.stock < item.quantity:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient stock for book {book.id}",
            )

    subtotal_cents = 0
    total_quantity = 0
    order_items = []

    # Only mutate stock after every validation has passed.
    for item, book in zip(data.items, books):
        line_total_cents = book.price_cents * item.quantity

        subtotal_cents += line_total_cents
        total_quantity += item.quantity
        book.stock -= item.quantity

        order_items.append(
            OrderItem(
                book_id=book.id,
                quantity=item.quantity,
                unit_price_cents=book.price_cents,
            )
        )

    discount_percent = calculate_discount_percent(member, total_quantity)
    discount_cents = subtotal_cents * discount_percent // 100
    total_cents = subtotal_cents - discount_cents

    order = Order(
        member_id=member.id,
        status=OrderStatus.PENDING.value,
        subtotal_cents=subtotal_cents,
        discount_percent=discount_percent,
        discount_cents=discount_cents,
        total_cents=total_cents,
        created_at=now,
        items=order_items,
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return order


def get_order(db: Session, order_id: int) -> Order:
    """Return an order by id, or raise 404."""
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def pay_order(db: Session, order_id: int) -> Order:
    """Mark a pending order as paid. 404 if missing; 409 if not pending."""
    order = get_order(db, order_id)
    if order.status != OrderStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"Cannot pay an order that is {order.status}")
    order.status = OrderStatus.PAID.value
    db.commit()
    db.refresh(order)
    return order


def cancel_order(db: Session, order_id: int) -> Order:
    """Cancel a pending order and restore its reserved stock."""

    order = get_order(db, order_id)

    if order.status != OrderStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel an order that is {order.status}",
        )

    for item in order.items:
        item.book.stock += item.quantity

    order.status = OrderStatus.CANCELLED.value

    db.commit()
    db.refresh(order)
    return order
