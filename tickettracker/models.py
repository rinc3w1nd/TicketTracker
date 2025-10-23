"""Database models for TicketTracker."""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, List, Sequence

from sqlalchemy import event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db


class TicketTag(db.Model):
    """Association table between tickets and tags."""

    __tablename__ = "ticket_tags"

    ticket_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey("tickets.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey("tags.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow, nullable=False)


class Ticket(db.Model):
    """Primary ticket object representing a task or request."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(db.String(255), nullable=False)
    description: Mapped[str] = mapped_column(db.Text, nullable=False)
    requester: Mapped[str | None] = mapped_column(db.String(120))
    _watchers: Mapped[str | None] = mapped_column("watchers", db.Text)
    priority: Mapped[str] = mapped_column(db.String(32), nullable=False, default="Medium")
    status: Mapped[str] = mapped_column(db.String(32), nullable=False, default="Open")
    due_date: Mapped[datetime | None] = mapped_column(db.DateTime)
    notes: Mapped[str | None] = mapped_column(db.Text)
    links: Mapped[str | None] = mapped_column(db.Text)
    on_hold_reason: Mapped[str | None] = mapped_column(db.String(255))
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    age_reference_date: Mapped[date | None] = mapped_column(
        db.Date,
        nullable=True,
        default=lambda: datetime.utcnow().date(),
    )

    updates: Mapped[List["TicketUpdate"]] = relationship(
        "TicketUpdate", back_populates="ticket", cascade="all, delete-orphan", order_by="TicketUpdate.created_at"
    )
    attachments: Mapped[List["Attachment"]] = relationship(
        "Attachment", back_populates="ticket", cascade="all, delete-orphan"
    )
    tags: Mapped[List["Tag"]] = relationship("Tag", secondary="ticket_tags", back_populates="tickets")

    @property
    def watchers(self) -> List[str]:
        if not self._watchers:
            return []
        return [part.strip() for part in self._watchers.split(",") if part.strip()]

    @watchers.setter
    def watchers(self, value: str | Sequence[str]) -> None:
        if isinstance(value, str):
            self._watchers = value
        else:
            self._watchers = ", ".join(part.strip() for part in value if part)

    @property
    def tag_names(self) -> List[str]:
        return [tag.name for tag in self.tags]

    def set_tags(self, tag_names: Iterable[str]) -> None:
        normalized = {name.strip() for name in tag_names if name.strip()}
        if not normalized:
            self.tags = []
            return

        existing = {tag.name: tag for tag in Tag.query.filter(Tag.name.in_(normalized)).all()}

        new_tags: List[Tag] = []
        for name in normalized:
            if name in existing:
                new_tags.append(existing[name])
            else:
                tag = Tag(name=name)
                db.session.add(tag)
                new_tags.append(tag)
        self.tags = new_tags

    def add_update(
        self,
        message: str,
        author: str | None = None,
        status_from: str | None = None,
        status_to: str | None = None,
        is_system: bool = False,
    ) -> "TicketUpdate":
        update = TicketUpdate(
            ticket=self,
            body=message,
            author=author,
            status_from=status_from,
            status_to=status_to,
            is_system=is_system,
        )
        db.session.add(update)
        self.updated_at = datetime.utcnow()
        return update


class TicketUpdate(db.Model):
    """Chronological updates associated with a ticket."""

    __tablename__ = "ticket_updates"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    body: Mapped[str] = mapped_column(db.Text, nullable=False)
    author: Mapped[str | None] = mapped_column(db.String(120))
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow, nullable=False)
    status_from: Mapped[str | None] = mapped_column(db.String(32))
    status_to: Mapped[str | None] = mapped_column(db.String(32))
    is_system: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False)

    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="updates")
    attachments: Mapped[List["Attachment"]] = relationship(
        "Attachment", back_populates="update", cascade="all, delete-orphan"
    )


class Attachment(db.Model):
    """Uploaded file stored on disk and linked to a ticket/update."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    update_id: Mapped[int | None] = mapped_column(db.Integer, db.ForeignKey("ticket_updates.id"))
    original_filename: Mapped[str] = mapped_column(db.String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(db.String(255), nullable=False)
    mimetype: Mapped[str | None] = mapped_column(db.String(128))
    size: Mapped[int | None] = mapped_column(db.Integer)
    checksum: Mapped[str | None] = mapped_column(db.String(64))
    file_uuid: Mapped[str | None] = mapped_column(db.String(36))
    uploaded_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow, nullable=False)

    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="attachments")
    update: Mapped[TicketUpdate | None] = relationship("TicketUpdate", back_populates="attachments")

    @property
    def display_name(self) -> str:
        return self.original_filename


class Tag(db.Model):
    """Reusable tag applied to tickets."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    color: Mapped[str | None] = mapped_column(db.String(16))

    tickets: Mapped[List[Ticket]] = relationship("Ticket", secondary="ticket_tags", back_populates="tags")


@event.listens_for(Ticket, "before_update")
def _touch_ticket(mapper, connection, target: Ticket) -> None:  # pragma: no cover - SQLAlchemy hook
    target.updated_at = datetime.utcnow()
