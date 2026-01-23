from kub_mitigation_agent.service.apps.hotel_reservation import HotelReservation

# Create instance (helm_deploy=True by default now)
app = HotelReservation()

# Deploy using Helm

app.cleanup()
app.deploy()  # This will call deploy_helm() internally

# Check status
print(f"Deployed: {app.is_deployed()}")
print(f"Services: {app.get_services()}")

# # Cleanup when done
# app.cleanup()