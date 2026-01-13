"""
Hotel Reservation traffic profile.

Based on DeathStarBench hotelReservation/wrk2/scripts/hotel-reservation/mixed-workload_type_1.lua

Simulates realistic hotel reservation user behavior with weighted endpoints:
- 60% hotel searches
- 39% recommendations
- 0.5% user logins
- 0.5% reservations
"""

import random
import logging
from locust import HttpUser, task, between

logger = logging.getLogger(__name__)


class HotelReservationUser(HttpUser):
    """
    Realistic Hotel Reservation user behavior.
    
    Each user maintains a persistent identity (user ID, username, password)
    throughout their session and makes requests with realistic parameter
    distributions matching real-world usage patterns.
    """
    
    # Wait 1-3 seconds between requests (realistic user pacing)
    wait_time = between(1, 3)
    
    # Connection settings
    connection_timeout = 10.0
    network_timeout = 10.0
    
    def on_start(self):
        """
        Initialize user session.
        
        Creates persistent user credentials that will be used
        for login and reservation operations.
        """
        # Generate user ID (0-500, matching original DeathStarBench script)
        self.user_id = random.randint(0, 500)
        self.username = f"Cornell_{self.user_id}"
        
        # Password is user_id repeated 10 times (as in original Lua script)
        self.password = str(self.user_id) * 10
        
        logger.debug(f"Hotel user session started: {self.username}")
    
    @task(60)  # 60% of requests - matches search_ratio in original script
    def search_hotel(self):
        """
        Search for available hotels.
        
        Generates random:
        - Check-in date: April 9-23, 2015
        - Check-out date: 1-15 days after check-in (up to April 24)
        - Location: Latitude/longitude near San Francisco Bay Area
        """
        # Random dates in April 2015
        in_date = random.randint(9, 23)
        out_date = random.randint(in_date + 1, 24)
        
        # Format dates as YYYY-MM-DD
        in_date_str = f"2015-04-{in_date:02d}"
        out_date_str = f"2015-04-{out_date:02d}"
        
        # Random location near San Francisco Bay Area
        # Base coordinates: 38.0235, -122.095
        # Small random offset to simulate different search locations
        lat = 38.0235 + (random.randint(0, 481) - 240.5) / 1000.0
        lon = -122.095 + (random.randint(0, 325) - 157.0) / 1000.0
        
        try:
            self.client.get(
                f"/hotels?inDate={in_date_str}&outDate={out_date_str}"
                f"&lat={lat:.4f}&lon={lon:.4f}",
                name="/hotels",
                timeout=10
            )
        except Exception as e:
            # Locust handles exceptions internally, just log for debugging
            logger.debug(f"Hotel search request failed: {e}")
    
    @task(39)  # 39% of requests - matches recommend_ratio in original script
    def recommend(self):
        """
        Get hotel recommendations.
        
        Generates random:
        - Requirement type: distance (33%), rate (33%), or price (33%)
        - Location: Latitude/longitude near San Francisco Bay Area
        """
        # Random requirement parameter (matches original Lua script distribution)
        coin = random.random()
        if coin < 0.33:
            req_param = "dis"    # Distance-based recommendations
        elif coin < 0.66:
            req_param = "rate"   # Rating-based recommendations
        else:
            req_param = "price"  # Price-based recommendations
        
        # Random location (same distribution as search)
        lat = 38.0235 + (random.randint(0, 481) - 240.5) / 1000.0
        lon = -122.095 + (random.randint(0, 325) - 157.0) / 1000.0
        
        try:
            self.client.get(
                f"/recommendations?require={req_param}&lat={lat:.4f}&lon={lon:.4f}",
                name="/recommendations",
                timeout=10
            )
        except Exception as e:
            logger.debug(f"Recommendation request failed: {e}")
    
    @task(1)  # 0.5% of requests (scaled to 1 for Locust task weighting)
    def user_login(self):
        """
        User login operation.
        
        Uses the user's persistent credentials (username, password)
        established in on_start().
        """
        try:
            self.client.post(
                f"/user?username={self.username}&password={self.password}",
                name="/user (login)",
                timeout=10
            )
        except Exception as e:
            logger.debug(f"User login failed: {e}")
    
    @task(1)  # 0.5% of requests (scaled to 1 for Locust task weighting)
    def reserve(self):
        """
        Make a hotel reservation.
        
        Generates random:
        - Check-in/out dates
        - Hotel ID (1-80, matching original script)
        - Number of rooms (always 1)
        
        Uses the user's credentials for the reservation.
        """
        # Random dates
        in_date = random.randint(9, 23)
        out_date = in_date + random.randint(1, 5)  # 1-5 day stay
        
        in_date_str = f"2015-04-{in_date:02d}"
        out_date_str = f"2015-04-{out_date:02d}"
        
        # Random hotel ID (1-80, as in original DeathStarBench script)
        hotel_id = random.randint(1, 80)
        
        # Note: lat/lon included in case backend uses them for validation
        lat = 38.0235 + (random.randint(0, 481) - 240.5) / 1000.0
        lon = -122.095 + (random.randint(0, 325) - 157.0) / 1000.0
        
        try:
            self.client.post(
                f"/reservation?inDate={in_date_str}&outDate={out_date_str}"
                f"&hotelId={hotel_id}&customerName={self.username}"
                f"&username={self.username}&password={self.password}&number=1",
                name="/reservation",
                timeout=10
            )
        except Exception as e:
            logger.debug(f"Reservation request failed: {e}")
