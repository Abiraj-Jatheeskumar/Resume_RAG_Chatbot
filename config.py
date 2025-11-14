"""
Configuration management for the RAG application.
"""
import os
from typing import Optional
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class Config:
    """Application configuration."""
    
    # API Keys
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    
    # Azure OpenAI Configuration
    AZURE_OPENAI_KEY: Optional[str] = os.getenv("AZURE_OPENAI_KEY")
    AZURE_OPENAI_ENDPOINT: Optional[str] = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_DEPLOYMENT: Optional[str] = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    
    # Model Configuration
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "azure_openai" if os.getenv("AZURE_OPENAI_KEY") else "openai").lower()
    LLM_MODEL: str = os.getenv("LLM_MODEL", os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"))
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "openai").lower()
    EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
    
    # Ollama Configuration
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama2")
    
    # Application Settings
    VECTOR_STORE_DIR: str = os.getenv("VECTOR_STORE_DIR", "./faiss_store")
    METADATA_FILE: str = os.getenv("METADATA_FILE", "./metadata.pkl")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Text Processing
    MAX_CHUNK_SIZE: int = int(os.getenv("MAX_CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "200"))
    MAX_DOCUMENTS: int = int(os.getenv("MAX_DOCUMENTS", "10000"))
    
    # Search Settings
    DEFAULT_K_RESULTS: int = int(os.getenv("DEFAULT_K_RESULTS", "5"))
    MAX_K_RESULTS: int = int(os.getenv("MAX_K_RESULTS", "20"))
    
    # UI Settings
    MAX_CHAT_HISTORY: int = int(os.getenv("MAX_CHAT_HISTORY", "10"))
    ENABLE_ANALYTICS: bool = os.getenv("ENABLE_ANALYTICS", "true").lower() == "true"
    
    @classmethod
    def validate(cls) -> bool:
        """Validate configuration settings."""
        errors = []
        
        if cls.LLM_PROVIDER == "openai" and not cls.OPENAI_API_KEY:
            logger.warning("OpenAI provider selected but no API key found. LLM features will be limited.")
        
        if cls.LLM_PROVIDER == "azure_openai":
            if not cls.AZURE_OPENAI_KEY:
                logger.warning("Azure OpenAI provider selected but no API key found. LLM features will be limited.")
            if not cls.AZURE_OPENAI_ENDPOINT:
                logger.warning("Azure OpenAI provider selected but no endpoint found. LLM features will be limited.")
            if not cls.AZURE_OPENAI_DEPLOYMENT:
                logger.warning("Azure OpenAI provider selected but no deployment name found. LLM features will be limited.")
        
        if cls.LLM_PROVIDER == "anthropic" and not cls.ANTHROPIC_API_KEY:
            logger.warning("Anthropic provider selected but no API key found. LLM features will be limited.")
        
        if cls.LLM_PROVIDER == "ollama":
            logger.info(f"Using Ollama at {cls.OLLAMA_BASE_URL}")
        
        if cls.MAX_CHUNK_SIZE < 100:
            errors.append("MAX_CHUNK_SIZE must be at least 100")
        
        if cls.CHUNK_OVERLAP >= cls.MAX_CHUNK_SIZE:
            errors.append("CHUNK_OVERLAP must be less than MAX_CHUNK_SIZE")
        
        if errors:
            for error in errors:
                logger.error(f"Configuration error: {error}")
            return False
        
        return True
    
    @classmethod
    def get_llm_config(cls) -> dict:
        """Get LLM configuration dictionary."""
        return {
            "provider": cls.LLM_PROVIDER,
            "model": cls.LLM_MODEL,
            "temperature": 0,
        }
    
    @classmethod
    def get_embedding_config(cls) -> dict:
        """Get embedding configuration dictionary."""
        return {
            "provider": cls.EMBEDDING_MODEL,
            "model_name": cls.EMBEDDING_MODEL_NAME,
        }


# Validate configuration on import
Config.validate()


