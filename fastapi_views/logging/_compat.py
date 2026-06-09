try:
    import structlog

    get_logger = structlog.get_logger

except ImportError:
    import logging

    get_logger = logging.getLogger
