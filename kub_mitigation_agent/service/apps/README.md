# Apps Package

App-specific configurations and traffic profiles for microservices under test.

## Structure

```
apps/
├── metadata/              # App configuration files (YAML)
│   └── hotel_reservation.yaml
├── profiles/              # Traffic patterns (Python/Locust)
│   ├── hotel_reservation.py
│   └── simple.py
├── base.py               # Base Application class
└── registry.py           # App discovery/registration
```

## Adding a New App

### 1. Create Metadata File

Create `metadata/my_app.yaml`:

```yaml
name: "My Application"
namespace: "my-app"
description: "My microservice application"

deployment:
  type: "kubernetes"
  manifest_dir: "kubernetes"

workload:
  profile: "my_app"
  default_users: 10
  spawn_rate: 2

observability:
  critical_services:
    - "frontend"
    - "backend"
```

### 2. Create Traffic Profile

Create `profiles/my_app.py`:

```python
from locust import HttpUser, task, between

class MyAppUser(HttpUser):
    wait_time = between(1, 3)
    
    @task
    def test_endpoint(self):
        self.client.get("/api/endpoint")
```

### 3. Register Profile

In `profiles/__init__.py`:

```python
from .my_app import MyAppUser

PROFILES["my_app"] = MyAppUser
```

### 4. Use in Config

```yaml
namespace: "my-app"
traffic_config:
  workload_pattern: "my_app"  # References profiles/my_app.py
```

Done! The system will automatically load the metadata and profile.

## Using Existing Profiles

### Hotel Reservation (Realistic)

```yaml
traffic_config:
  workload_pattern: "hotel_reservation"
  host: "http://ingress:80"
  num_users: 10
```

Simulates realistic user behavior:
- 60% hotel searches
- 39% recommendations
- 0.5% logins
- 0.5% reservations

### Simple (Basic Testing)

```yaml
traffic_config:
  workload_pattern: "simple"
  host: "http://ingress:80"
  endpoints:
    - "/endpoint1"
    - "/endpoint2"
```

Tests specified endpoints with equal probability.
