"""Reporting queries."""
from typing import List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Book, Order, OrderItem, OrderStatus
from app.schemas import TopBook


def top_books(db: Session, limit: int) -> List[TopBook]:
    """Return the best-selling books from paid orders only."""

    copies_sold = func.sum(OrderItem.quantity)

    rows = db.execute(
        select(
            Book.id.label("book_id"),
            Book.title,
            copies_sold.label("copies_sold"),
        )
        .join(OrderItem, OrderItem.book_id == Book.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status == OrderStatus.PAID.value)
        .group_by(Book.id, Book.title)
        .order_by(
            copies_sold.desc(),
            Book.title.asc(),
        )
        .limit(limit)
    ).all()

    return [
        TopBook(
            book_id=row.book_id,
            title=row.title,
            copies_sold=int(row.copies_sold),
        )
        for row in rows
    ]
