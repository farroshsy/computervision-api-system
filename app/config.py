"""Application configuration and environment variables."""
import os
from typing import List, Optional, Union, Literal
from pydantic import field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging
from typing import List, Optional
from pydantic import field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and configuration."""
    
    # CORS Configuration
    CORS_ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="List of allowed CORS origins"
    )
    
    # API Configuration
    API_KEY: str = Field(
        default="your_secure_api_key_here",
        description="API key for authenticating requests"
    )
    
    # File Upload Configuration
    MAX_UPLOAD_BYTES: int = Field(
        default=10 * 1024 * 1024,  # 10 MB
        description="Maximum allowed file upload size in bytes"
    )
    
    # Logging Configuration
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    LOG_FILE: str = Field(
        default="app.log",
        description="Path to log file, or empty string to disable file logging"
    )
    LOG_FORMAT: str = Field(
        default="json",
        description="Log format: 'json' or 'text'"
    )
    
    # Request Configuration
    REQUEST_TIMEOUT: int = Field(
        default=30,
        description="Request timeout in seconds"
    )
    
    # File Validation Configuration
    MIN_IMAGE_SHORT_SIDE: int = Field(
        default=600,
        description="Images whose short side is below this get the advisory reason resolution_too_low"
    )
    PHOTOCOPY_SATURATION_THRESHOLD: float = Field(
        default=3.0,
        description="Mean HSV saturation below this flags grayscale_possible_photocopy (copies/scans ~0-2, real photos >=4)"
    )
    EVIDENCE_DIR: str = Field(
        default="evidence",
        description="Runtime-mounted folder with generated evidence/report HTML (PII - never in the image); served at /demo/evidence"
    )
    ALLOWED_MIME_TYPES: List[str] = Field(
        default=["image/jpeg", "image/png", "image/jpg", "image/webp", "application/pdf"],
        description="List of allowed MIME types for file uploads"
    )
    
    # Document Type Validation
    ALLOWED_DOCUMENT_TYPES: List[str] = Field(
        default=["AUTO", "KTP", "SIM", "STNK", "KIR"],
        description="List of allowed document types for processing"
    )
    
    # Rate Limiting Configuration
    RATE_LIMIT_ENABLED: bool = Field(
        default=True,
        description="Enable or disable rate limiting globally"
    )
    GLOBAL_RATE_LIMIT: int = Field(
        default=100,
        description="Global rate limit (requests per minute per IP)"
    )
    API_KEY_RATE_LIMIT: int = Field(
        default=1000,
        description="Rate limit per API key (requests per minute)"
    )
    RATE_LIMIT_BYPASS_KEYS: List[str] = Field(
        default_factory=list,
        description="List of API keys that bypass rate limiting"
    )
    
    # Security Settings
    REQUIRE_API_KEY: bool = Field(
        default=True,
        description="Whether API key is required for authentication"
    )
    RATE_LIMIT: int = Field(
        default=100,
        description="Maximum requests per minute per IP (not yet implemented)"
    )
    
    # Environment Configuration
    ENVIRONMENT: str = Field(
        default="development",
        description="Current environment (development, staging, production)"
    )
    
    # Metrics Configuration
    ENABLE_METRICS: bool = Field(
        default=True,
        description="Whether to enable Prometheus metrics collection"
    )
    METRICS_ENABLED: bool = Field(
        default=True,
        description="Alias for ENABLE_METRICS for backward compatibility"
    )
    METRICS_PATH: str = Field(
        default="/metrics",
        description="Path to expose Prometheus metrics"
    )
    METRICS_EXCLUDE_HEALTH: bool = Field(
        default=True,
        description="Whether to exclude health checks from metrics"
    )
    METRICS_EXCLUDE_DOCS: bool = Field(
        default=True,
        description="Whether to exclude API documentation from metrics"
    )
    
    # Rate Limiting Configuration
    RATE_LIMITING_ENABLED: bool = Field(
        default=True,
        description="Whether rate limiting is enabled"
    )

    # Parser behavior flags (make extraction configurable)
    PARSER_STRICT_ADMIN_FILTER: bool = Field(
        default=True,
        description="If true, aggressively reject lines containing admin/province/header tokens"
    )
    PARSER_ENFORCE_VOWEL_CHECK: bool = Field(
        default=True,
        description="If true, reject non-partial place/address tokens without vowels (anti-gibberish)"
    )
    PARSER_ALLOW_STANDALONE_ADDRESS: bool = Field(
        default=True,
        description="If true, allow standalone address fallback using street cues when label not found"
    )
    PARSER_ALLOW_STANDALONE_KELURAHAN: bool = Field(
        default=True,
        description="If true, allow standalone kelurahan/desa fallback when label not found"
    )
    # OCR pipeline selection and thresholds
    OCR_PIPELINE_MODE: str = Field(
        default="baseline",
        description="OCR pipeline mode: 'baseline' (current) or 'cascade' (baseline + detector fallback)"
    )
    LOW_CONF_THRESHOLD: float = Field(
        default=0.70,
        description="Confidence threshold below which fields are considered weak and may trigger fallback"
    )
    MAX_FALLBACKS: int = Field(
        default=1,
        description="Maximum number of fallback attempts (e.g., detector-guided re-OCR)"
    )
    MIN_FIELDS_FOR_PASS: int = Field(
        default=3,
        description="Minimum number of populated fields to consider a parse sufficiently rich"
    )
    # Confidence thresholds and retry behavior
    GLOBAL_MIN_CONFIDENCE: float = Field(
        default=0.50,
        description="Global minimum confidence floor across fields"
    )
    MIN_CONF_ALAMAT: float = Field(default=0.60, description="Minimum confidence for alamat")
    MIN_CONF_KELURAHAN_DESA: float = Field(default=0.70, description="Minimum confidence for kelurahan/desa")
    MIN_CONF_RT_RW: float = Field(default=0.65, description="Minimum confidence for RT/RW")
    RELAXED_RETRY_ENABLED: bool = Field(
        default=True,
        description="If true, perform relaxed pass for missing fields with looser filters"
    )
    RESPONSE_INCLUDE_PROVENANCE: bool = Field(
        default=False,
        description="If true, include provenance and confidence in API/parse responses"
    )
    OCR_QUALITY_SUGGESTION_THRESHOLD: float = Field(
        default=0.35,
        description="If OCR quality below this, attach user-facing retake suggestions"
    )
    
    # Pydantic configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    @property
    def LOG_LEVEL_NUM(self) -> int:
        """Convert log level string to logging module constant."""
        return getattr(logging, self.LOG_LEVEL.upper(), logging.INFO)
    
    @field_validator('CORS_ALLOWED_ORIGINS', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS origins from string to list if needed."""
        if isinstance(v, str):
            # Handle JSON array string
            if v.startswith('[') and v.endswith(']'):
                import json
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    pass
            # Handle comma-separated string
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v
    
    @field_validator('LOG_LEVEL')
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate that LOG_LEVEL is a valid logging level."""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of {', '.join(valid_levels)}")
        return v.upper()
    
    @field_validator('LOG_FORMAT')
    @classmethod
    def validate_log_format(cls, v: str) -> str:
        """Validate that LOG_FORMAT is either 'json' or 'text'."""
        if v.lower() not in ['json', 'text']:
            raise ValueError("LOG_FORMAT must be either 'json' or 'text'")
        return v.lower() or []


# Create settings instance
settings = Settings()
