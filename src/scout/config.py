import os
import logging
from dataclasses import dataclass, field

from scout.filters import FilterConfig
from scout.validation import SnippetValidationConfig

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    pass


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Required environment variable {name} is not set")
    return value


def get_optional_env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class RedditConfig:
    client_id: str = field(default_factory=lambda: get_required_env("REDDIT_CLIENT_ID"))
    client_secret: str = field(
        default_factory=lambda: get_required_env("REDDIT_CLIENT_SECRET")
    )
    user_agent: str = field(
        default_factory=lambda: get_optional_env("REDDIT_USER_AGENT", "scout/0.1")
    )
    rate_limit_per_minute: int = 60
    request_delay_seconds: float = 1.0


@dataclass
class HackerNewsConfig:
    rate_limit_per_minute: int = 30
    request_delay_seconds: float = 0.5
    max_comments_per_story: int = 100
    comment_depth_limit: int = 5
    hits_per_page: int = 100


@dataclass
class LLMConfig:
    model: str = "gpt-4o"
    extraction_model: str = "gpt-4o"
    extraction_prompt_version: str = "v1"
    complexity_model: str = "gpt-4o-mini"
    temperature: float = 0.0
    max_tokens: int = 4096


@dataclass
class ScoutConfig:
    data_dir: str = field(
        default_factory=lambda: get_optional_env("SCOUT_DATA_DIR", "data/sessions")
    )
    max_iterations: int = 60
    max_documents: int = 200
    saturation_threshold: float = 0.2
    saturation_window: int = 10
    saturation_empty_extractions_limit: int = 5
    saturation_signal_diversity_threshold: float = 0.6
    saturation_min_entities: int = 20
    parallel_workers: int = 5
    deep_comments: str = "auto"
    max_cost_usd: float | None = None
    filter: FilterConfig = field(default_factory=FilterConfig)
    snippet_validation: SnippetValidationConfig = field(
        default_factory=SnippetValidationConfig
    )
    reddit: RedditConfig | None = None
    hackernews: HackerNewsConfig = field(default_factory=HackerNewsConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    @classmethod
    def from_env(cls, sources: list[str] | None = None) -> "ScoutConfig":
        sources = sources or ["hackernews"]
        reddit_config = None
        if "reddit" in sources:
            reddit_config = RedditConfig()
        return cls(reddit=reddit_config)

    @classmethod
    def from_profile(
        cls, profile: str, sources: list[str] | None = None
    ) -> "ScoutConfig":
        profiles = {
            "quick": {
                "max_iterations": 5,
                "max_documents": 200,
                "saturation_threshold": 0.5,
                "parallel_workers": 5,
                "deep_comments": "never",
            },
            "standard": {
                "max_iterations": 60,
                "max_documents": 200,
                "saturation_threshold": 0.2,
                "parallel_workers": 5,
            },
            "deep": {
                "max_iterations": 150,
                "max_documents": 500,
                "saturation_threshold": 0.15,
                "parallel_workers": 8,
                "deep_comments": "always",
            },
        }
        if profile not in profiles:
            raise ConfigError(f"Unknown profile: {profile}")
        config = cls.from_env(sources=sources)
        for key, value in profiles[profile].items():
            setattr(config, key, value)
        return config

    def validate(self, sources: list[str] | None = None) -> None:
        sources = sources or ["hackernews"]
        if self.max_iterations < 1:
            raise ConfigError("max_iterations must be at least 1")
        if self.max_documents < 1:
            raise ConfigError("max_documents must be at least 1")
        if not 0 <= self.saturation_threshold <= 1:
            raise ConfigError("saturation_threshold must be between 0 and 1")
        if self.saturation_empty_extractions_limit < 1:
            raise ConfigError("saturation_empty_extractions_limit must be at least 1")
        if not 0 <= self.saturation_signal_diversity_threshold <= 1:
            raise ConfigError(
                "saturation_signal_diversity_threshold must be between 0 and 1"
            )
        if self.saturation_min_entities < 0:
            raise ConfigError("saturation_min_entities must be >= 0")
        if self.parallel_workers < 1:
            raise ConfigError("parallel_workers must be at least 1")
        if self.max_cost_usd is not None and self.max_cost_usd <= 0:
            raise ConfigError("max_cost_usd must be > 0 when set")
        if self.filter.min_content_length < 0:
            raise ConfigError("filter.min_content_length must be >= 0")
        if self.filter.min_score < 0:
            raise ConfigError("filter.min_score must be >= 0")
        if not 0.0 <= self.snippet_validation.min_confidence <= 1.0:
            raise ConfigError(
                "snippet_validation.min_confidence must be between 0 and 1"
            )
        if self.snippet_validation.min_excerpt_length < 0:
            raise ConfigError("snippet_validation.min_excerpt_length must be >= 0")
        if self.snippet_validation.min_pain_statement_length < 0:
            raise ConfigError(
                "snippet_validation.min_pain_statement_length must be >= 0"
            )
        if self.deep_comments not in ("auto", "always", "never"):
            raise ConfigError("deep_comments must be 'auto', 'always', or 'never'")
        from scout.prompts import EXTRACTION_PROMPTS

        if self.llm.extraction_prompt_version not in EXTRACTION_PROMPTS:
            raise ConfigError(
                f"Unknown extraction_prompt_version: {self.llm.extraction_prompt_version}"
            )
        if "reddit" in sources and self.reddit is None:
            raise ConfigError(
                "Reddit config required but REDDIT_CLIENT_ID/SECRET not set"
            )
        logger.info("Configuration validated successfully")
