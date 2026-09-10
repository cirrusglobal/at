"""Application settings, loaded from the environment (and .env for local dev)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- AWS ---
    aws_region: str = "eu-central-1"
    # Credentials deliberately absent: boto3's default provider chain resolves
    # them from the SSO profile, environment, or instance role. Never from here.

    # --- Persistence ---
    dynamodb_table_name: str = "networks"
    # Set to e.g. http://localhost:8001 for DynamoDB Local; None uses real AWS.
    dynamodb_endpoint_url: str | None = None
    # Convenience for local development only. In AWS the table is created by
    # Terraform, and the deployed role has no CreateTable permission.
    auto_create_table: bool = False

    # --- Auth ---
    # Dev default only, and long enough to satisfy RFC 7518 §3.2 for HS256.
    # Generate a real one with: openssl rand -hex 32
    jwt_secret: str = "dev-only-insecure-secret-change-me-before-deploying"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "vpc-provisioning-api"
    jwt_audience: str = "vpc-provisioning-api"
    access_token_ttl_minutes: int = 60

    # Seeded single user so a reviewer can get a token without provisioning an
    # identity provider. See README for the Cognito swap.
    demo_username: str = "demo"
    demo_password: str = "demo-password"

    # Applied as a tag to every resource this service creates, so anything it
    # provisions can be found (and cleaned up) later.
    managed_by_tag: str = "vpc-provisioning-api"


@lru_cache
def get_settings() -> Settings:
    return Settings()
