"""Logging helpers used by the platform's verbose request logging setup."""

import logging


class RequestContextFormatter(logging.Formatter):
    """Always include a request id, including for startup and migration logs."""

    def format(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return super().format(record)
