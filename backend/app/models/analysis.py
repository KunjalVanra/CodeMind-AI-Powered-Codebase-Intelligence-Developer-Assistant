
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    func
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import relationship

from app.core.database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    repository_id = Column(
        Integer,
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    status = Column(String(50), default="pending")

    summary = Column(
        Text().with_variant(LONGTEXT(), "mysql"),
        nullable=True
    )

    total_files = Column(Integer, default=0)

    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    completed_at = Column(DateTime, nullable=True)

    user = relationship(
        "User",
        back_populates="analyses"
    )

    repository = relationship(
        "Repository",
        back_populates="analyses"
    )
