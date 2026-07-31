"""Deterministic metadata extraction from document text."""

import re
from datetime import datetime
from typing import Any

from src.logging_config import get_logger

logger = get_logger(__name__)


class MetadataExtractor:
    """Extracts structured metadata from document text using regex patterns."""

    # Patterns for requirement IDs: REQ-123, REQ_123, Requirement-123, etc.
    REQUIREMENT_PATTERN = re.compile(
        r"(?:REQ|REQUIREMENT|Req)[\s_-]*(\d{3,6})",
        re.IGNORECASE,
    )

    # Patterns for change request IDs: CR-1234, CR_1234, CR#1234, etc.
    CHANGE_REQUEST_PATTERN = re.compile(
        r"(?:CR|CHANGE[\s_-]*REQUEST)[\s#_-]*(\d{3,6})",
        re.IGNORECASE,
    )

    # Patterns for project names: common prefixes followed by descriptive text
    PROJECT_NAME_PATTERN = re.compile(
        r"(?:Project|Program|Initiative)[\s:]+([A-Z][A-Za-z0-9\s\-]+?)(?:\n|$|\.|,)",
    )

    # Date patterns: various common formats
    DATE_PATTERNS = [
        re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),  # 2024-01-15
        re.compile(r"\b(\d{2}/\d{2}/\d{4})\b"),  # 01/15/2024
        re.compile(r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b"),  # 15 Jan 2024
    ]

    # Repository references
    REPO_PATTERN = re.compile(
        r"(?:https?://)?(?:github\.com|gitlab\.com|bitbucket\.org|dev\.azure\.com)/[\w.-]+/[\w.-]+",
    )

    # Email / contributor patterns
    EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

    # Version patterns
    VERSION_PATTERN = re.compile(r"(?:[Vv]ersion|[Vv])\s*(\d+\.\d+(?:\.\d+)?)")

    def extract(self, text: str) -> dict[str, Any]:
        """Extract all metadata from document text.

        Returns a dict with keys like:
            requirement_ids, change_request_ids, project_names,
            dates, repositories, emails, versions
        """
        metadata: dict[str, Any] = {
            "requirement_ids": self._extract_requirements(text),
            "change_request_ids": self._extract_change_requests(text),
            "project_names": self._extract_project_names(text),
            "dates": self._extract_dates(text),
            "repositories": self._extract_repositories(text),
            "contributors": self._extract_contributors(text),
            "versions": self._extract_versions(text),
        }
        return metadata

    def _extract_requirements(self, text: str) -> list[str]:
        matches = self.REQUIREMENT_PATTERN.findall(text)
        return sorted(set(f"REQ-{m}" for m in matches))

    def _extract_change_requests(self, text: str) -> list[str]:
        matches = self.CHANGE_REQUEST_PATTERN.findall(text)
        return sorted(set(f"CR-{m}" for m in matches))

    def _extract_project_names(self, text: str) -> list[str]:
        matches = self.PROJECT_NAME_PATTERN.findall(text)
        return sorted(set(m.strip() for m in matches if len(m.strip()) > 3))

    def _extract_dates(self, text: str) -> list[str]:
        dates: set[str] = set()
        for pattern in self.DATE_PATTERNS:
            dates.update(pattern.findall(text))
        return sorted(dates)[:50]  # Cap at 50 dates

    def _extract_repositories(self, text: str) -> list[str]:
        return sorted(set(self.REPO_PATTERN.findall(text)))

    def _extract_contributors(self, text: str) -> list[str]:
        return sorted(set(self.EMAIL_PATTERN.findall(text)))

    def _extract_versions(self, text: str) -> list[str]:
        return sorted(set(self.VERSION_PATTERN.findall(text)))
