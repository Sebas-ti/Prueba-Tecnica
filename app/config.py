"""Configuración centralizada de la aplicación.

Toda la configuración se lee de variables de entorno (o de un archivo .env en
desarrollo). Ningún secreto se escribe en código. En Azure, los secretos llegan
como referencias a Key Vault desde Container Apps, o directamente se evitan
usando Managed Identity (DefaultAzureCredential).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Aplicación ---------------------------------------------------------
    app_name: str = "IC7 Enterprise RAG Agent"
    environment: Literal["local", "dev", "test", "prod"] = "local"
    log_level: str = "INFO"

    # --- Selección de proveedores ------------------------------------------
    # "azure" usa servicios gestionados; "local" permite ejecutar todo sin nube.
    llm_provider: Literal["azure", "local"] = "local"
    vector_store_provider: Literal["azure_search", "local"] = "local"
    history_provider: Literal["cosmos", "sqlite"] = "sqlite"

    # --- Azure OpenAI -------------------------------------------------------
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None  # vacío => Managed Identity
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_chat_deployment: str = "gpt-4o-mini"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # --- Azure AI Search ----------------------------------------------------
    azure_search_endpoint: str | None = None
    azure_search_api_key: SecretStr | None = None  # vacío => Managed Identity
    azure_search_index: str = "ic7-knowledge"

    # --- Azure Cosmos DB ----------------------------------------------------
    cosmos_endpoint: str | None = None
    cosmos_key: SecretStr | None = None  # vacío => Managed Identity
    cosmos_database: str = "ragagent"
    cosmos_container: str = "interactions"

    # --- Observabilidad -----------------------------------------------------
    applicationinsights_connection_string: SecretStr | None = None

    # --- Almacenamiento local ----------------------------------------------
    data_dir: str = "data"
    index_dir: str = "storage/index"
    sqlite_path: str = "storage/history.db"
    requests_db_path: str = "data/solicitudes.json"
    cloud_catalog_path: str = "data/cloud_services.json"

    # --- RAG ----------------------------------------------------------------
    chunk_size: int = Field(default=900, ge=200, le=4000)  # caracteres
    chunk_overlap: int = Field(default=150, ge=0, le=1000)
    top_k: int = Field(default=4, ge=1, le=20)
    # Score mínimo (0-1, coseno normalizado) para considerar que hay contexto
    # suficiente. Por debajo, el asistente responde "no tengo información".
    min_relevance_score: float = Field(default=0.30, ge=0.0, le=1.0)

    # --- Agente -------------------------------------------------------------
    agent_max_iterations: int = Field(default=5, ge=1, le=10)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    llm_max_tokens: int = Field(default=800, ge=64, le=4096)

    # --- Seguridad ----------------------------------------------------------
    # Lista separada por comas. Vacío en local => auth deshabilitada (se avisa
    # en el log). En dev/prod se exige al menos una clave.
    api_keys: SecretStr | None = None
    max_question_chars: int = 2000
    max_upload_mb: int = 10
    allowed_extensions: str = ".pdf,.docx,.md,.txt"
    rate_limit_per_minute: int = 60
    cors_origins: str = ""

    @property
    def api_key_set(self) -> set[str]:
        if not self.api_keys:
            return set()
        return {k.strip() for k in self.api_keys.get_secret_value().split(",") if k.strip()}

    @property
    def allowed_extension_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_extensions.split(",") if e.strip()}

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap debe ser menor que chunk_size")
        if self.llm_provider == "azure" and not self.azure_openai_endpoint:
            raise ValueError("LLM_PROVIDER=azure requiere AZURE_OPENAI_ENDPOINT")
        if self.vector_store_provider == "azure_search":
            if not self.azure_search_endpoint:
                raise ValueError("VECTOR_STORE_PROVIDER=azure_search requiere AZURE_SEARCH_ENDPOINT")
            if self.llm_provider != "azure":
                # Los embeddings locales (hashing) no son compatibles con un
                # índice gestionado de 1536 dimensiones.
                raise ValueError("azure_search requiere LLM_PROVIDER=azure (embeddings de Azure OpenAI)")
        if self.history_provider == "cosmos" and not self.cosmos_endpoint:
            raise ValueError("HISTORY_PROVIDER=cosmos requiere COSMOS_ENDPOINT")
        if self.environment in {"dev", "prod"} and not self.api_key_set:
            raise ValueError("En dev/prod se requiere API_KEYS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
