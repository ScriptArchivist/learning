# service/logging_filter.py
from __future__ import annotations

import logging

from service.correlation import get_request_id, get_trace_id


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.request_id = get_request_id() or "-"
        except Exception:
            record.request_id = "-"

        try:
            record.trace_id = get_trace_id() or "-"
        except Exception:
            record.trace_id = "-"

        return True