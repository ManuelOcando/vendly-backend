"""
Unit tests for the bot personality presets.

The bug these guard against: per-tenant personality never worked. The handler
read bot_personality from whatsapp_configs (no such column) and json.loads() the
result, while the real column holds prose. Every tenant silently got the settings
defaults.
"""
import pytest

from services.bot_personalities import (
    AUTO,
    DEFAULT_BOT_PERSONALITY_PROMPT,
    PRESETS,
    default_preset_for_industry,
    has_custom_prompt,
    knobs_for_preset,
    knobs_from_settings,
    preset_names,
    resolve_personality,
)

PROVIDER_KNOBS = {"tone", "use_emojis", "greeting_style"}


class TestPresets:
    def test_every_preset_carries_the_three_provider_knobs(self):
        # The providers read exactly these keys; a preset missing one would
        # silently fall back to a hardcoded default inside the provider.
        for name, preset in PRESETS.items():
            assert PROVIDER_KNOBS <= set(preset), f"{name} is missing a knob"

    def test_every_preset_has_a_label_and_a_sample_for_onboarding(self):
        for name, preset in PRESETS.items():
            assert preset.get("label"), f"{name} has no label"
            assert preset.get("sample"), f"{name} has no sample"

    def test_greeting_styles_accept_the_store_name_placeholder(self):
        # The providers call greeting_style.format(store_name=...); a stray
        # brace would raise there, inside prompt building.
        for name, preset in PRESETS.items():
            formatted = preset["greeting_style"].format(store_name="Mi Tienda")
            assert "Mi Tienda" in formatted, f"{name} drops the store name"

    def test_preset_names_match_the_migration_020_check_constraint(self):
        # Adding a preset here without widening the CHECK constraint would make
        # onboarding write a value the database rejects.
        assert set(preset_names()) == {"calido", "formal", "directo", "divertido"}
        assert AUTO not in preset_names()


class TestDefaultPresetForIndustry:
    @pytest.mark.parametrize("industry,expected", [
        ("restaurant", "calido"),
        ("retail", "directo"),
        ("services", "formal"),
        ("RESTAURANT", "calido"),
    ])
    def test_known_industries(self, industry, expected):
        assert default_preset_for_industry(industry) == expected

    @pytest.mark.parametrize("industry", [None, "", "something-else"])
    def test_unknown_industry_still_returns_a_real_preset(self, industry):
        assert default_preset_for_industry(industry) in PRESETS


class TestHasCustomPrompt:
    def test_column_default_is_not_a_custom_prompt(self):
        # tenants.bot_personality ships with this prose as its default, so
        # treating any non-empty value as bespoke would give every tenant a
        # "custom" personality.
        assert has_custom_prompt(DEFAULT_BOT_PERSONALITY_PROMPT) is False
        assert has_custom_prompt(f"  {DEFAULT_BOT_PERSONALITY_PROMPT}  ") is False

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_values(self, value):
        assert has_custom_prompt(value) is False

    def test_hand_written_prompt(self):
        assert has_custom_prompt("Habla como un sommelier.") is True


class TestResolvePersonality:
    def test_always_returns_the_provider_knobs(self):
        assert PROVIDER_KNOBS <= set(resolve_personality(None))

    def test_auto_resolves_from_the_industry(self):
        personality = resolve_personality({
            "type": "services",
            "bot_personality_preset": AUTO,
        })
        assert personality["preset"] == "formal"
        assert personality["tone"] == PRESETS["formal"]["tone"]

    def test_missing_preset_column_behaves_like_auto(self):
        # A tenants row selected before migration 020, or one where the column
        # came back NULL.
        personality = resolve_personality({"type": "restaurant"})
        assert personality["preset"] == "calido"

    def test_chosen_preset_beats_the_industry_default(self):
        personality = resolve_personality({
            "type": "restaurant",
            "bot_personality_preset": "formal",
        })
        assert personality["preset"] == "formal"
        assert personality["use_emojis"] is False

    def test_unknown_preset_falls_back_to_the_industry(self):
        personality = resolve_personality({
            "type": "retail",
            "bot_personality_preset": "inventado",
        })
        assert personality["preset"] == "directo"

    def test_custom_prompt_wins_and_knobs_survive(self):
        # custom_prompt replaces the personality block, but the knobs stay in
        # the dict so a provider that ignores it still works.
        personality = resolve_personality({
            "type": "retail",
            "bot_personality_preset": "formal",
            "bot_personality": "Habla como un sommelier.",
        })
        assert personality["custom_prompt"] == "Habla como un sommelier."
        assert PROVIDER_KNOBS <= set(personality)

    def test_column_default_prompt_does_not_become_a_custom_prompt(self):
        personality = resolve_personality({
            "type": "restaurant",
            "bot_personality": DEFAULT_BOT_PERSONALITY_PROMPT,
        })
        assert "custom_prompt" not in personality

    def test_settings_defaults_are_reachable(self):
        assert PROVIDER_KNOBS <= set(knobs_from_settings())
        assert PROVIDER_KNOBS <= set(knobs_for_preset(None))
