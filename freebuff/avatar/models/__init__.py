"""Avatar model backends — abstract interface and implementations."""

from freebuff.avatar.models.base import AvatarBackend
from freebuff.avatar.models.sadtalker import SadTalkerBackend

__all__ = ["AvatarBackend", "SadTalkerBackend"]
