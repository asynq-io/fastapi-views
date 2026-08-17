try:
    import structlog

    get_logger = structlog.get_logger
    is_structlog = True

except ImportError:
    import logging

    get_logger = logging.getLogger
    is_structlog = False
