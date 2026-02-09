#!/usr/bin/env python3
"""
Test script for Open5GS 5G Core deployment.

This script cleans up any existing deployments, then deploys Open5GS fresh.
"""

import time
from kub_mitigation_agent.service.apps import Open5GS


def main():
    """Deploy and test Open5GS 5G Core."""
    print("=" * 60)
    print("Open5GS 5G Core Deployment Test")
    print("=" * 60)
    
    # Initialize application
    app = Open5GS()
    
    print(f"\n📋 Application Summary:")
    print(app.get_app_summary())
    
    # Clean up any existing deployments
    if app.is_deployed():
        print(f"\n🧹 Cleaning up existing deployment in namespace: {app.namespace}")
        try:
            app.cleanup()
            print(f"   ✅ Cleanup completed")
            time.sleep(5)  # Wait for cleanup to complete
        except Exception as e:
            print(f"   ⚠️  Cleanup warning: {e}")
    else:
        print(f"\n✨ No existing deployment found - starting fresh")
    
    # Deploy
    print(f"\n🚀 Deploying Open5GS to namespace: {app.namespace}")
    app.deploy()
    
    # Check deployment
    print(f"\n✅ Deployment Status:")
    print(f"   - Deployed: {app.is_deployed()}")
    print(f"   - Services: {', '.join(app.get_services())}")
    print(f"   - Core Functions: {', '.join(app.get_core_functions())}")
    
    print(f"\n💡 To deploy UERANSIM for traffic generation:")
    print(f"   app.deploy_ueransim()")
    
    print(f"\n💡 To list UEs (after deploying UERANSIM):")
    print(f"   app.list_ues()")
    
    print(f"\n💡 To establish PDU session:")
    print(f"   app.establish_pdu_session('imsi-999700000000001')")
    
    print(f"\n💡 To cleanup:")
    print(f"   app.delete()  # or app.cleanup() for full namespace deletion")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
