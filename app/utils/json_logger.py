"""Structured JSON logging configuration."""
import logging
import sys
import json
from datetime import datetime
import pythonjsonlogger.json as jsonlogger
from typing import Any, Dict, Optional

from app.config import settings


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter that includes additional fields."""
    
    def add_fields(
        self, 
        log_record: Dict[str, Any], 
        record: logging.LogRecord, 
        message_dict: Dict[str, Any]
    ) -> None:
        """Add custom fields to the log record."""
        super().add_fields(log_record, record, message_dict)
        
        # Add timestamp in ISO format
        log_record["timestamp"] = datetime.utcnow().isoformat()
        
        # Add log level
        log_record["level"] = record.levelname
        
        # Add logger name
        log_record["logger"] = record.name
        
        # Add request ID if available
        if hasattr(record, 'request_id'):
            log_record["request_id"] = record.request_id
        
        # Add process and thread information
        log_record["process"] = record.process
        log_record["thread"] = record.thread
        log_record["thread_name"] = record.threadName


def setup_logging() -> None:
    """Configure logging with JSON formatter and appropriate handlers."""
    # Remove all existing handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Configure the root logger
    root_logger.setLevel(settings.LOG_LEVEL)
    
    # Create formatter
    formatter = CustomJsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s',
        timestamp=True
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler if log file is specified
    if settings.LOG_FILE and settings.LOG_FILE.lower() != 'none':
        file_handler = logging.FileHandler(settings.LOG_FILE)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Configure uvicorn logger to use our formatter
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers = []
    uvicorn_logger.propagate = True
    
    # Configure uvicorn access logger
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers = []
    uvicorn_access.propagate = True
    
    # Disable noisy loggers
    logging.getLogger("uvicorn.error").propagate = False
    logging.getLogger("uvicorn.error").handlers = []
    
    # Configure our application logger
    app_logger = logging.getLogger("app")
    app_logger.setLevel(settings.LOG_LEVEL)
    
    return app_logger


# Initialize logger
logger = setup_logging()
