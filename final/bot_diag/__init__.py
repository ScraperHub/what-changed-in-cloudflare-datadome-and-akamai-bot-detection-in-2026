"""Diagnose Crawlbase responses and measure usable data."""

from bot_diag.classify import classify_response
from bot_diag.client import CrawlClient, parse_response
from bot_diag.escalation import plan_action
from bot_diag.evaluate import evaluate_urls, summarize
from bot_diag.routing import route_domain

__version__ = "1.0.0"

__all__ = [
    "CrawlClient",
    "classify_response",
    "evaluate_urls",
    "parse_response",
    "plan_action",
    "route_domain",
    "summarize",
]
