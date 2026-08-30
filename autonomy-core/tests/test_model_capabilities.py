from dronedream_agent_core.model_port import ProviderSettings, StructuredModelPort


def _port(provider: str, model: str, *, explicit: bool | None = None) -> StructuredModelPort:
    return StructuredModelPort(
        provider,
        settings=ProviderSettings(
            name=provider,
            model=model,
            api_key_env="TEST_API_KEY",
            base_url="https://example.invalid/v1",
            api_style="chat-completions",
            supports_image_input=explicit,
        ),
        api_key="test-key",
    )


def test_deepseek_is_not_silently_treated_as_visual() -> None:
    assert _port("deepseek", "deepseek-v4-flash").supports_image_input is False


def test_known_visual_models_and_explicit_capability_are_routable() -> None:
    assert _port("openai", "gpt-5.4").supports_image_input is True
    assert _port("qwen", "qwen3-vl-plus").supports_image_input is True
    assert _port("custom", "text-model", explicit=True).supports_image_input is True


def test_unknown_openai_compatible_model_fails_closed_for_images() -> None:
    assert _port("custom", "text-model").supports_image_input is False
