
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Repository(Base):
    __tablename__ = "repositories"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "github_url",
            name="unique_user_repository"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    github_url = Column(String(500), nullable=False)

    name = Column(String(255), nullable=False)

    owner_name = Column(String(255), nullable=False)

    default_branch = Column(String(100), default="main")

    status = Column(String(50), default="connected")

    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    owner = relationship(
        "User",
        back_populates="repositories"
    )

    analyses = relationship(
        "Analysis",
        back_populates="repository",
        cascade="all, delete-orphan"
    )
