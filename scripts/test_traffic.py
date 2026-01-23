#!/usr/bin/env python3
"""Enhanced traffic test script for Hotel Reservation app with detailed metrics."""

# IMPORTANT: gevent monkey patching must happen BEFORE any other imports
# to avoid SSL recursion errors with locust
from gevent import monkey
monkey.patch_all()

import asyncio
import time
import requests
from kub_mitigation_agent.service.apps import HotelReservation
from kub_mitigation_agent.generators.workload.locust_generator import LocustTrafficGenerator

def test_endpoint(url, description):
    """Test a single endpoint and return status."""
    try:
        response = requests.get(url, timeout=5)
        return f"✅ {description}: {response.status_code}"
    except Exception as e:
        return f"❌ {description}: {str(e)[:50]}"

def print_stats(generator):
    """Print current Locust statistics."""
    if not generator.runner or not generator.environment:
        return
    
    stats = generator.environment.stats
    print("\n📊 Current Statistics:")
    print("=" * 80)
    print(f"{'Endpoint':<30} {'Requests':<10} {'Failures':<10} {'Avg (ms)':<12} {'RPS':<8}")
    print("-" * 80)
    
    for stat in stats.entries.values():
        avg_response = stat.avg_response_time if stat.num_requests > 0 else 0
        rps = stat.current_rps
        print(f"{stat.name:<30} {stat.num_requests:<10} {stat.num_failures:<10} "
              f"{avg_response:<12.0f} {rps:<8.1f}")
    
    total = stats.total
    total_avg = total.avg_response_time if total.num_requests > 0 else 0
    print("-" * 80)
    print(f"{'TOTAL':<30} {total.num_requests:<10} {total.num_failures:<10} "
          f"{total_avg:<12.0f} {total.current_rps:<8.1f}")
    print("=" * 80)

async def main():
    """Run an enhanced traffic test with detailed monitoring."""
    
    # Get app instance
    app = HotelReservation()
    
    # Check if app is deployed
    if not app.is_deployed():
        print("❌ Hotel Reservation is not deployed. Run test_hotel_deployment.py first.")
        return
    
    print("✅ Hotel Reservation is deployed")
    print(f"   Namespace: {app.namespace}")
    print(f"   Services: {', '.join(app.get_services()[:5])}... ({len(app.get_services())} total)")
    
    # Frontend URL
    frontend_url = "http://localhost:8080"
    
    # Test basic connectivity
    print(f"\n🔍 Testing frontend connectivity...")
    print(f"   Target: {frontend_url}")
    print(test_endpoint(f"{frontend_url}/", "Root endpoint"))
    print(test_endpoint(
        f"{frontend_url}/hotels?inDate=2015-04-15&outDate=2015-04-16&lat=38.0&lon=-122.0",
        "Hotel search"
    ))
    print(test_endpoint(
        f"{frontend_url}/recommendations?require=dis&lat=38.0&lon=-122.0",
        "Recommendations"
    ))
    
    # Create traffic generator with hotel_reservation profile
    print(f"\n🚀 Starting traffic test...")
    config = {
        "workload_pattern": "hotel_reservation",
        "host": frontend_url,
        "num_users": 10,           # 10 concurrent users
        "spawn_rate": 2,           # Spawn 2 users per second
        "wait_time_min": 1,
        "wait_time_max": 3,
    }
    
    print(f"   Users: {config['num_users']}")
    print(f"   Spawn rate: {config['spawn_rate']} users/second")
    print(f"   Wait time: {config['wait_time_min']}-{config['wait_time_max']}s between requests")
    print(f"   Expected RPS: ~{config['num_users'] / ((config['wait_time_min'] + config['wait_time_max']) / 2):.1f}")
    
    generator = LocustTrafficGenerator(config)
    
    # Start traffic
    await generator.start_traffic()
    
    # Wait for users to spawn
    print("\n⏱️  Spawning users...")
    await asyncio.sleep(6)  # Wait for all users to spawn
    
    # Monitor traffic for 30 seconds with periodic stats
    print("\n📈 Generating traffic (will show stats every 10 seconds)...")
    duration = 30
    interval = 10
    
    for i in range(0, duration, interval):
        await asyncio.sleep(interval)
        elapsed = i + interval
        print(f"\n⏱️  {elapsed}/{duration} seconds elapsed")
        print_stats(generator)
    
    # Final stats
    print(f"\n⏱️  {duration}/{duration} seconds - Test complete!")
    print_stats(generator)
    
    # Stop traffic
    print("\n🛑 Stopping traffic...")
    await generator.stop_traffic()
    
    # Summary
    if generator.environment:
        stats = generator.environment.stats.total
        success_rate = ((stats.num_requests - stats.num_failures) / stats.num_requests * 100) if stats.num_requests > 0 else 0
        
        print("\n" + "=" * 80)
        print("📊 TEST SUMMARY")
        print("=" * 80)
        print(f"Total requests:    {stats.num_requests}")
        print(f"Total failures:    {stats.num_failures}")
        print(f"Success rate:      {success_rate:.1f}%")
        print(f"Average response:  {stats.avg_response_time:.0f}ms")
        print(f"Min response:      {stats.min_response_time:.0f}ms")
        print(f"Max response:      {stats.max_response_time:.0f}ms")
        print("=" * 80)
    
    print("\n✅ Traffic test complete!")
    print("\n💡 Tip: Check detailed service logs with:")
    print(f"   kubectl logs -n {app.namespace} -l service=frontend --tail=100")

if __name__ == "__main__":
    print("=" * 80)
    print("Hotel Reservation - Enhanced Traffic Test")
    print("=" * 80)
    asyncio.run(main())
