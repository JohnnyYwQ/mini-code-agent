from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnthropicLLMConfig:
    api_key: str
    model: str
    max_tokens: int
    base_url: str | None = None

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("api_key must not be empty")
        if not self.model:
            raise ValueError("model must not be empty")
        if (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens <= 0
        ):
            raise ValueError("max_tokens must be a positive integer")
