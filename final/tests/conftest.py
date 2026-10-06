import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: calls the Crawlbase API; skipped unless CRAWLBASE_TOKEN is set and the URL host is example.com",
    )
