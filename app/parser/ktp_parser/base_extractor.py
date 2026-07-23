"""
Base Extractor Module

This module contains the base FieldExtractor class that all field extractors inherit from.
"""

from abc import ABC, abstractmethod
import logging
from typing import Any, Optional

from app.models.schemas import ParserContext

logger = logging.getLogger(__name__)

class FieldExtractor(ABC):
    """Base class for all field extractors"""
    
    def __init__(self, field_name: str):
        """
        Initialize the field extractor.
        
        Args:
            field_name: The name of the field this extractor handles
        """
        self.field_name = field_name
    
    @abstractmethod
    def extract(self, context: ParserContext) -> Optional[str]:
        """
        Extract a single field from the context.
        
        Args:
            context: The parser context containing lines and extracted fields
            
        Returns:
            Extracted field value or None if not found
        """
        pass
    
    def _log_extraction(self, context: ParserContext, value: Any, **kwargs) -> None:
        """
        Helper method for consistent logging.
        
        Args:
            context: The parser context
            value: The extracted value
            **kwargs: Additional context for logging
        """
        self._log_info(
            context,
            f"Extracted {self.field_name}",
            value=value,
            **kwargs
        )
    
    def _log_info(self, context: ParserContext, message: str, **kwargs) -> None:
        """
        Helper method for info logging.
        
        Args:
            context: The parser context
            message: The info message
            **kwargs: Additional context for logging
        """
        if context and hasattr(context, 'log_info'):
            context.log_info(message, **kwargs)
        else:
            items = " | ".join(f"{k}={v}" for k, v in kwargs.items())
            logger.info(f"{message} | {items}")
    
    def _log_debug(self, context: ParserContext, message: str, **kwargs) -> None:
        """
        Helper method for debug logging.
        
        Args:
            context: The parser context
            message: The debug message
            **kwargs: Additional context for logging
        """
        if context and hasattr(context, 'log_debug'):
            context.log_debug(message, **kwargs)
        else:
            items = " | ".join(f"{k}={v}" for k, v in kwargs.items())
            logger.debug(f"{message} | {items}")
    
    def _log_warning(self, context: ParserContext, message: str, **kwargs) -> None:
        """
        Helper method for warning logging.
        
        Args:
            context: The parser context
            message: The warning message
            **kwargs: Additional context for logging
        """
        if context and hasattr(context, 'log_warning'):
            context.log_warning(message, **kwargs)
        else:
            items = " | ".join(f"{k}={v}" for k, v in kwargs.items())
            logger.warning(f"{message} | {items}")
    
    def _log_error(self, context: ParserContext, message: str, **kwargs) -> None:
        """
        Helper method for error logging.
        
        Args:
            context: The parser context
            message: The error message
            **kwargs: Additional context for logging
        """
        if context and hasattr(context, 'log_error'):
            context.log_error(message, **kwargs)
        else:
            items = " | ".join(f"{k}={v}" for k, v in kwargs.items())
            logger.error(f"{message} | {items}")
