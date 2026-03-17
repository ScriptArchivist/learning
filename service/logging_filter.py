import logging


class CorrelationFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return True