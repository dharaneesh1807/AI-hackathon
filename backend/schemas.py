import re
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import AwareDatetime, BaseModel, Field, field_validator


class Input(BaseModel):
    model_config = {'str_strip_whitespace': True, 'extra': 'forbid'}


class EmailInput(Input):
    email: str = Field(min_length=3, max_length=254)

    @field_validator('email')
    @classmethod
    def email_format(cls, value):
        value = value.lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email address')
        return value


class Register(EmailInput):
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=128)


class Login(EmailInput):
    password: str = Field(min_length=1, max_length=128)


class ProfileInput(Input):
    name: str = Field(min_length=1, max_length=100)
    timezone: str = 'Asia/Kolkata'

    @field_validator('timezone')
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Use an IANA timezone, e.g. Asia/Kolkata')
        return value


class InviteInput(EmailInput):
    role: Literal['caregiver', 'family']


class JoinInput(Input):
    code: str = Field(min_length=12, max_length=80)


class MedicationInput(Input):
    name: str = Field(min_length=1, max_length=120)
    dosage: str = Field(min_length=1, max_length=120)
    times: list[str] = Field(min_length=1, max_length=12)
    instructions: str = Field(default='', max_length=1000)

    @field_validator('times')
    @classmethod
    def valid_times(cls, values):
        if any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', v) for v in values):
            raise ValueError('Times must be HH:MM, using the 24-hour clock')
        return sorted(set(values))


class AppointmentInput(Input):
    title: str = Field(min_length=1, max_length=150)
    doctor: str = Field(min_length=1, max_length=120)
    starts_at: AwareDatetime
    location: str = Field(default='', max_length=200)

    @field_validator('starts_at')
    @classmethod
    def to_utc(cls, value: datetime):
        return value.astimezone(timezone.utc)
