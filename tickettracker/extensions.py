"""Application extensions for TicketTracker."""
from flask_sqlalchemy import SQLAlchemy

# SQLAlchemy database instance shared across the application.
db = SQLAlchemy()
