#!/usr/bin/env python3
"""
Launch the Agent UI Server for trace visualization.

Usage:
    python scripts/run_ui.py                    # Default settings
    python scripts/run_ui.py --port 8080        # Custom port
    python scripts/run_ui.py --logs-dir ./data  # Custom logs directory
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Launch the KubMitigation Agent UI Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_ui.py                     # Start on http://localhost:8888
  python scripts/run_ui.py --port 3000         # Start on http://localhost:3000
  python scripts/run_ui.py --logs-dir ./data   # Use custom logs directory
  python scripts/run_ui.py --reload            # Enable auto-reload for development
        """
    )
    
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )
    
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8888,
        help="Port to listen on (default: 8888)"
    )
    
    parser.add_argument(
        "--logs-dir", "-l",
        type=str,
        default="DATASET_LOGS",
        help="Directory containing experiment logs (default: DATASET_LOGS)"
    )
    
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    
    return parser.parse_args()


def main():
    """Run the UI server."""
    args = parse_arguments()
    
    try:
        from kub_mitigation_agent.ui import run_server
        
        run_server(
            host=args.host,
            port=args.port,
            logs_dir=args.logs_dir,
            reload=args.reload
        )
    except ImportError as e:
        print(f"\nError: Missing required dependencies.")
        print(f"Please install the required packages:")
        print(f"  pip install fastapi uvicorn")
        print(f"\nDetails: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nServer stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
