"""Test if namespace labeling works correctly."""
import sys
from kub_mitigation_agent.service.apps.hotel_reservation import HotelReservation
from kub_mitigation_agent.service.kubectl import KubeCtl

print("=" * 60)
print("Testing HotelReservation namespace labeling")
print("=" * 60)

# Delete namespace first
print("\n1. Cleaning up existing namespace...")
kubectl = KubeCtl()
kubectl.delete_namespace("hotel-reservation")
print("   Namespace deleted")

# Create new instance
print("\n2. Creating HotelReservation instance...")
app = HotelReservation()
print(f"   App name: {app.name}")
print(f"   Namespace: {app.namespace}")
print(f"   Istio injection enabled: {app.istio_injection_enabled}")

# Check namespace label
print("\n3. Checking namespace label...")
result = kubectl.exec_command("kubectl get namespace hotel-reservation -o jsonpath='{.metadata.labels.istio-injection}'")
print(f"   istio-injection label value: '{result.strip()}'")

if result.strip() == "enabled":
    print("\n✅ SUCCESS: Namespace has istio-injection=enabled label!")
else:
    print("\n❌ FAILED: Namespace does NOT have istio-injection=enabled label")
    print("\n   Checking all labels:")
    all_labels = kubectl.exec_command("kubectl get namespace hotel-reservation --show-labels")
    print(f"   {all_labels}")

print("\n4. Now testing deploy...")
app.deploy()

print("\n5. Checking namespace label after deploy...")
result = kubectl.exec_command("kubectl get namespace hotel-reservation -o jsonpath='{.metadata.labels.istio-injection}'")
print(f"   istio-injection label value: '{result.strip()}'")

if result.strip() == "enabled":
    print("\n✅ SUCCESS: Namespace still has istio-injection=enabled label after deploy!")
else:
    print("\n❌ FAILED: Namespace lost the label after deploy")
