"""Readers for each supported hiring system; `registry` is the entry point for the pipeline."""

from hungry_hunt.adapters.careers import job_links, jsonld_postings
from hungry_hunt.adapters.greenhouse import description as greenhouse_description
from hungry_hunt.adapters.html import html_posting, html_to_text
from hungry_hunt.adapters.registry import SUPPORTED, AtsSource, board_url, list_jobs
from hungry_hunt.adapters.workday import posted_days as workday_posted_days
from hungry_hunt.core.http import BoardError

__all__ = [
    "SUPPORTED",
    "AtsSource",
    "BoardError",
    "board_url",
    "greenhouse_description",
    "html_posting",
    "html_to_text",
    "job_links",
    "jsonld_postings",
    "list_jobs",
    "workday_posted_days",
]
