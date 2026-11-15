from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(Text)


class Profile(Base):
    __tablename__ = 'profiles'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(80))


class Membership(Base):
    __tablename__ = 'memberships'
    __table_args__ = (UniqueConstraint('profile_id', 'user_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey('profiles.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    role: Mapped[str] = mapped_column(String(16))


class Invitation(Base):
    __tablename__ = 'invitations'
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey('profiles.id'), index=True)
    email: Mapped[str] = mapped_column(String(254))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[int]
    used: Mapped[bool] = mapped_column(default=False)


class Medication(Base):
    __tablename__ = 'medications'
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey('profiles.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    dosage: Mapped[str] = mapped_column(String(120))
    times: Mapped[str] = mapped_column(Text)  # comma-separated HH:MM local times
    instructions: Mapped[str] = mapped_column(Text, default='')


class Appointment(Base):
    __tablename__ = 'appointments'
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey('profiles.id'), index=True)
    title: Mapped[str] = mapped_column(String(150))
    doctor: Mapped[str] = mapped_column(String(120))
    starts_at: Mapped[str] = mapped_column(String(40))  # UTC ISO-8601
    location: Mapped[str] = mapped_column(String(200), default='')


class Dose(Base):
    """A historical snapshot, independent of later prescription edits/deletion."""
    __tablename__ = 'doses'
    __table_args__ = (UniqueConstraint('profile_id', 'medication_id', 'due_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey('profiles.id'), index=True)
    medication_id: Mapped[int] = mapped_column(index=True)
    medication_name: Mapped[str] = mapped_column(String(120))
    dosage: Mapped[str] = mapped_column(String(120))
    instructions: Mapped[str] = mapped_column(Text)
    due_at: Mapped[int] = mapped_column(index=True)  # UTC epoch seconds
    status: Mapped[str] = mapped_column(String(20), default='scheduled')
    follow_up: Mapped[str] = mapped_column(String(16), default='none')
    claimed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    version: Mapped[int] = mapped_column(default=0)


class CareEvent(Base):
    __tablename__ = 'care_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey('profiles.id'), index=True)
    dose_id: Mapped[int] = mapped_column(ForeignKey('doses.id'), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(32))
    at: Mapped[int] = mapped_column(index=True)
    note: Mapped[str] = mapped_column(Text, default='')


class EmailPreference(Base):
    __tablename__ = 'email_preferences'
    __table_args__ = (UniqueConstraint('profile_id', 'user_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey('profiles.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    enabled: Mapped[bool] = mapped_column(default=False)


class EmailAttempt(Base):
    __tablename__ = 'email_attempts'
    __table_args__ = (UniqueConstraint('profile_id', 'user_id', 'event_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey('profiles.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    event_key: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default='dispatched')
    created_at: Mapped[int]
