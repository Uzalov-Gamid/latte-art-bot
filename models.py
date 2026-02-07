"""
Database models for Latte Art Competition Bot.
Uses SQLAlchemy ORM with async support.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text, Enum as SQLEnum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


class UserLevel(enum.Enum):
    """LAGS levels for users."""
    WHITE = "White"
    ORANGE = "Orange"
    GREEN = "Green"
    RED = "Red"
    BLACK = "Black"
    GOLD = "Gold"


class SubmissionStatus(enum.Enum):
    """Status of a submission."""
    PENDING = "pending"
    EVALUATED = "evaluated"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


class ChallengeStatus(enum.Enum):
    """Status of a challenge."""
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed" 


class User(Base):
    """User/Participant model."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(100))
    nickname = Column(String(100), nullable=False)
    city = Column(String(100))
    coffee_shop = Column(String(50))
    level = Column(SQLEnum(UserLevel), default=UserLevel.WHITE)
    points = Column(Integer, default=0)
    submissions_count = Column(Integer, default=0)
    evaluated_submissions_count = Column(Integer, default=0)
    registration_date = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)
    is_banned = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    language = Column(String(10), default="ru")

    # Relationships
    submissions = relationship(
        "Submission", back_populates="user", cascade="all, delete-orphan")
    evaluations = relationship("Evaluation", back_populates="admin_user")

    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id}, nickname={self.nickname}, level={self.level.value})>"


class Submission(Base):
    """Submission model for latte art photos."""
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    challenge_id = Column(Integer, ForeignKey("challenges.id"), nullable=True)
    photo_file_id = Column(String(200), nullable=False)
    description = Column(Text)
    status = Column(SQLEnum(SubmissionStatus),
                    default=SubmissionStatus.PENDING)
    submission_date = Column(DateTime, default=datetime.utcnow)

    # Scores (averaged if multiple admins evaluate)
    visual_quality = Column(Float, default=0.0)
    creativity = Column(Float, default=0.0)
    technical_skills = Column(Float, default=0.0)
    overall_harmony = Column(Float, default=0.0)
    total_score = Column(Float, default=0.0)
    level_achieved = Column(SQLEnum(UserLevel), nullable=True)
    admin_comment = Column(Text)

    # Relationships
    user = relationship("User", back_populates="submissions")
    challenge = relationship("Challenge", back_populates="submissions")
    evaluations = relationship(
        "Evaluation", back_populates="submission", cascade="all, delete-orphan")
    likes = relationship("Like", back_populates="submission",
                         cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Submission(id={self.id}, user_id={self.user_id}, status={self.status.value})>"


class Evaluation(Base):
    """Individual evaluation by an admin."""
    __tablename__ = "evaluations"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey(
        "submissions.id"), nullable=False)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    visual_quality = Column(Float, nullable=False)
    creativity = Column(Float, nullable=False)
    technical_skills = Column(Float, nullable=False)
    overall_harmony = Column(Float, nullable=False)
    total_score = Column(Float, nullable=False)
    comment = Column(Text)
    evaluation_date = Column(DateTime, default=datetime.utcnow)

    # Relationships
    submission = relationship("Submission", back_populates="evaluations")
    admin_user = relationship("User", back_populates="evaluations")

    def __repr__(self):
        return f"<Evaluation(id={self.id}, submission_id={self.submission_id}, total={self.total_score})>"


class Challenge(Base):
    """Challenge/Competition model."""
    __tablename__ = "challenges"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    theme = Column(String(200))
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    status = Column(SQLEnum(ChallengeStatus), default=ChallengeStatus.PLANNED)
    prizes = Column(Text)
    winner_1_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    winner_2_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    winner_3_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow)

    # Relationships
    submissions = relationship("Submission", back_populates="challenge")

    def __repr__(self):
        return f"<Challenge(id={self.id}, name={self.name}, status={self.status.value})>"


class Like(Base):
    """Like model for submissions (for popularity ranking)."""
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey(
        "submissions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    like_date = Column(DateTime, default=datetime.utcnow)

    # Relationships
    submission = relationship("Submission", back_populates="likes")

    def __repr__(self):
        return f"<Like(submission_id={self.submission_id}, user_id={self.user_id})>"


class AdminSession(Base):
    """Admin session tracking for login attempts."""
    __tablename__ = "admin_sessions"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    is_logged_in = Column(Boolean, default=False)
    login_attempts = Column(Integer, default=0)
    last_attempt = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<AdminSession(telegram_id={self.telegram_id}, is_logged_in={self.is_logged_in})>"


class BotSettings(Base):
    """Bot configuration settings."""
    __tablename__ = "bot_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<BotSettings(key={self.key}, value={self.value})>"
