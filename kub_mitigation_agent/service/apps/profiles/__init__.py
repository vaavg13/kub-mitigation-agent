"""
Traffic profiles for applications.

Each profile defines realistic user behavior patterns using Locust HttpUser classes.
"""

from typing import Dict, Type
from locust import HttpUser

from .hotel_reservation import HotelReservationUser
from .simple import SimpleLoadUser


# Profile registry
PROFILES: Dict[str, Type[HttpUser]] = {
    "hotel_reservation": HotelReservationUser,
    "simple": SimpleLoadUser,
}


def get_profile(pattern: str) -> Type[HttpUser]:
    """
    Get Locust user class for a traffic pattern.
    
    Args:
        pattern: Pattern name (e.g., 'hotel_reservation', 'simple')
    
    Returns:
        Locust HttpUser subclass
    
    Raises:
        ValueError: If pattern is not found
    """
    if pattern not in PROFILES:
        available = ", ".join(PROFILES.keys())
        raise ValueError(
            f"Unknown traffic profile: '{pattern}'. "
            f"Available profiles: {available}"
        )
    return PROFILES[pattern]


def register_profile(name: str, user_class: Type[HttpUser]):
    """
    Register a custom traffic profile.
    
    Args:
        name: Profile name
        user_class: Locust HttpUser subclass
    """
    PROFILES[name] = user_class


def list_profiles() -> Dict[str, Type[HttpUser]]:
    """
    List all registered traffic profiles.
    
    Returns:
        Dict mapping profile name to user class
    """
    return PROFILES.copy()


__all__ = [
    "HotelReservationUser",
    "SimpleLoadUser",
    "PROFILES",
    "get_profile",
    "register_profile",
    "list_profiles",
]
