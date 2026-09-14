import os
import ssl
from dataclasses import dataclass, field
from .common import PipelineError


@dataclass(frozen=True)
class Settings:
    state_path: str
    provider: str
    model: str
    api_key: str = field(repr=False)
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str = field(repr=False)
    neo4j_database: str
    api_token: str = field(repr=False)
    daily_calls: int
    run_calls: int

    @classmethod
    def from_env(cls, env_file=None):
        if env_file:
            from dotenv import load_dotenv

            if not load_dotenv(env_file, override=True):
                raise PipelineError("pipeline_env_file_empty_or_missing")
        provider = os.getenv("EXTRACTION_PROVIDER", "anthropic")
        if provider not in ("openai", "anthropic"):
            raise PipelineError("invalid_extraction_provider")
        daily = int(os.getenv("PIPELINE_DAILY_CALLS", "20"))
        run = int(os.getenv("PIPELINE_RUN_CALLS", "3"))
        if not 1 <= daily <= 10000 or not 1 <= run <= daily:
            raise PipelineError("invalid_extraction_budget")
        return cls(
            os.getenv("PIPELINE_DATABASE_URL")
            or os.getenv("PIPELINE_STATE_PATH", "research_state/pico.sqlite3"),
            provider,
            os.getenv("EXTRACTION_MODEL", ""),
            os.getenv(
                "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY", ""
            ),
            os.getenv("NEO4J_URI", ""),
            os.getenv("NEO4J_USERNAME") or os.getenv("NEO4J_USER", ""),
            os.getenv("NEO4J_PASSWORD", ""),
            os.getenv("NEO4J_DATABASE", "neo4j"),
            os.getenv("PIPELINE_API_TOKEN", ""),
            daily,
            run,
        )

    def graph(self):
        if not all((self.neo4j_uri, self.neo4j_username, self.neo4j_password)):
            raise PipelineError("neo4j_configuration_missing")
        from neo4j import GraphDatabase

        # Python.org macOS installations may have no default CA file. Keep
        # verification enabled, and respect an explicitly configured CA bundle.
        if not ssl.get_default_verify_paths().cafile and not os.getenv("SSL_CERT_FILE"):
            import certifi

            os.environ["SSL_CERT_FILE"] = certifi.where()

        return GraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_username, self.neo4j_password),
            connection_timeout=15,
            max_transaction_retry_time=15,
        )
