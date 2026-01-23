"""Centralized path definitions for the project."""

from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent  # kub_mitigation_agent/
PROJECT_ROOT = BASE_DIR.parent              # kub-mitigation-agent/

# Application directories
TARGET_MICROSERVICES = PROJECT_ROOT / "helm-chart"
DEATHSTARBENCH_DIR = PROJECT_ROOT / "DeathStarBench"

# Service directories
SERVICE_DIR = BASE_DIR / "service"
APP_METADATA_DIR = SERVICE_DIR / "apps" / "metadata"
APP_PROFILES_DIR = SERVICE_DIR / "apps" / "profiles"

# Generator directories
GENERATORS_DIR = BASE_DIR / "generators"
FAULT_GENERATORS_DIR = GENERATORS_DIR / "fault"
WORKLOAD_GENERATORS_DIR = GENERATORS_DIR / "workload"

# Specific app metadata files
HOTEL_RESERVATION_METADATA = APP_METADATA_DIR / "hotel_reservation.json"
HOTEL_RESERVATION_EXPERIMENTS = APP_METADATA_DIR / "hotel_reservation_experiments.yaml"

# Experiment settings
EXPERIMENT_SETTINGS = BASE_DIR / "experiment_settings.yaml"

# Configuration directories
CONFIG_DIR = PROJECT_ROOT / "experiment_configs"

# Data directories
DATA_DIR = PROJECT_ROOT / "DATA"
EXPERIMENT_LOGS_DIR = PROJECT_ROOT / "experiment_logs"
REPORTS_DIR = PROJECT_ROOT / "REPORTS"

# DeathStarBench-specific paths
DSB_HOTEL_RES_DIR = DEATHSTARBENCH_DIR / "hotelReservation"
DSB_SOCIAL_NET_DIR = DEATHSTARBENCH_DIR / "socialNetwork"
DSB_MEDIA_DIR = DEATHSTARBENCH_DIR / "mediaMicroservices"
DSB_WRK2_DIR = DEATHSTARBENCH_DIR / "wrk2"
