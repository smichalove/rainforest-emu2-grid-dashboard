"""Global pytest configuration for rainforest-emu2-grid-dashboard.

Applies macOS proxy resolution bypass and AWS metadata disabling
to eliminate network latency during testing.
"""

import os
import urllib.request

urllib.request.getproxies = lambda: {}
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
