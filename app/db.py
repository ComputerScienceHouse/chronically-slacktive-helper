"""PostgreSQL database models and session management."""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

db_engine = None
DBSession = None
Base = declarative_base()


def init_db(database_url: str):
    """Initialize the database engine and session factory.

    Args:
        database_url: SQLAlchemy database URL string.
    """
    global db_engine, DBSession
    db_engine = create_engine(
        database_url,
        pool_size=5,
        max_overflow=10,
    )
    DBSession = sessionmaker(bind=db_engine)
    Base.metadata.create_all(db_engine)


def get_session():
    """Return a new session bound to the engine."""
    return DBSession()
