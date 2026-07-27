"""
Unit tests for the multi-language support module (spec requirement 15).
"""
import re
import pytest

from services.i18n import (
    DEFAULT_LANGUAGE,
    INTENT_KEYWORDS,
    MESSAGES,
    SUPPORTED_LANGUAGES,
    detect_language,
    keywords_for,
    matches_exact_intent,
    matches_intent,
    matches_word_intent,
    normalize_language,
    t,
)

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


class TestDetectLanguage:
    @pytest.mark.parametrize("text,expected", [
        ("hola, quiero una hamburguesa", "es"),
        ("buenos dias, cuanto cuesta?", "es"),
        ("gracias!", "es"),
        ("hello, I want a burger", "en"),
        ("good morning, how much is it?", "en"),
        ("thanks!", "en"),
        ("ola, quero um hamburguer", "pt"),
        ("bom dia, quanto custa?", "pt"),
        ("obrigado", "pt"),
    ])
    def test_detects_supported_languages(self, text, expected):
        assert detect_language(text) == expected

    @pytest.mark.parametrize("text", ["", "ok", "1", "42", "xyzzy", "...", "👍"])
    def test_returns_none_when_no_signal(self, text):
        """None means 'keep the conversation's current language' - guessing
        here would snap an English conversation back to Spanish on a stray
        'ok'."""
        assert detect_language(text) is None

    def test_orthographic_signals(self):
        assert detect_language("mañana") == "es"
        assert detect_language("promoção") == "pt"

    def test_accented_spanish_question(self):
        assert detect_language("¿dónde está mi pedido?") == "es"


class TestNormalizeLanguage:
    @pytest.mark.parametrize("value,expected", [
        (None, DEFAULT_LANGUAGE),
        ("", DEFAULT_LANGUAGE),
        ("es", "es"),
        ("EN", "en"),
        ("pt-BR", "pt"),
        ("pt_BR", "pt"),
        ("fr", DEFAULT_LANGUAGE),
        ("garbage", DEFAULT_LANGUAGE),
    ])
    def test_coerces_to_supported_code(self, value, expected):
        assert normalize_language(value) == expected


class TestTranslate:
    def test_returns_requested_language(self):
        assert t("menu.empty", "en") == "There are no products available right now."

    def test_falls_back_to_spanish_for_unsupported_language(self):
        assert t("menu.empty", "fr") == MESSAGES["menu.empty"]["es"]

    def test_missing_key_returns_key(self):
        """Visible but harmless - a typo shows up as the key instead of
        crashing a live conversation."""
        assert t("does.not.exist", "en") == "does.not.exist"

    def test_formats_placeholders(self):
        result = t("product.not_found", "en", name="burger")
        assert "burger" in result

    def test_missing_placeholder_does_not_raise(self):
        result = t("product.not_found", "en")
        assert isinstance(result, str)

    def test_defaults_to_spanish(self):
        assert t("menu.empty") == MESSAGES["menu.empty"]["es"]


class TestCatalogCompleteness:
    """Guards against typos across ~250 hand-written translations."""

    def test_every_key_has_every_language(self):
        missing = [
            f"{key}:{lang}"
            for key, translations in MESSAGES.items()
            for lang in SUPPORTED_LANGUAGES
            if not translations.get(lang)
        ]
        assert missing == []

    def test_placeholders_match_across_languages(self):
        mismatched = []
        for key, translations in MESSAGES.items():
            expected = set(PLACEHOLDER_RE.findall(translations[DEFAULT_LANGUAGE]))
            for lang in SUPPORTED_LANGUAGES:
                found = set(PLACEHOLDER_RE.findall(translations[lang]))
                if found != expected:
                    mismatched.append(f"{key}:{lang} {sorted(found)} != {sorted(expected)}")
        assert mismatched == []

    def test_no_unexpected_languages(self):
        extra = [
            f"{key}:{lang}"
            for key, translations in MESSAGES.items()
            for lang in translations
            if lang not in SUPPORTED_LANGUAGES
        ]
        assert extra == []

    def test_every_intent_has_every_language(self):
        missing = [
            f"{intent}:{lang}"
            for intent, by_language in INTENT_KEYWORDS.items()
            for lang in SUPPORTED_LANGUAGES
            if not by_language.get(lang)
        ]
        assert missing == []


class TestMatchesIntent:
    @pytest.mark.parametrize("message", [
        "estado de mi pedido",
        "where is my order",
        "onde esta meu pedido",
    ])
    def test_order_status_across_languages(self, message):
        assert matches_intent(message, "order_status")

    def test_matches_regardless_of_session_language(self):
        """Customers mix languages - an English 'yes' in a Spanish
        conversation must still confirm."""
        assert matches_intent("yes", "confirm")
        assert matches_intent("sim", "confirm")

    def test_accent_insensitive(self):
        assert matches_intent("devolucion", "return")
        assert matches_intent("devolución", "return")

    def test_language_scoped_lookup(self):
        assert matches_intent("where is my order", "order_status", language="en")
        assert not matches_intent("where is my order", "order_status", language="es")

    def test_no_match(self):
        assert not matches_intent("quiero una hamburguesa", "order_status")

    def test_empty_message(self):
        assert not matches_intent("", "confirm")


class TestMatchesExactIntent:
    def test_exact_match(self):
        assert matches_exact_intent("si", "confirm")
        assert matches_exact_intent("hoy", "today")

    def test_rejects_substring(self):
        assert not matches_exact_intent("no quiero eso", "reject")

    def test_tomorrow_across_languages(self):
        for word in ("mañana", "tomorrow", "amanha"):
            assert matches_exact_intent(word, "tomorrow")


class TestMatchesWordIntent:
    def test_matches_standalone_word(self):
        assert matches_word_intent("sí quiero", "confirm")
        assert matches_word_intent("no gracias", "reject")

    def test_does_not_fire_inside_other_words(self):
        """The bug this exists to prevent: a bare substring "no" matches
        inside "normal", silently cancelling a customer's order."""
        assert not matches_word_intent("normal", "reject")
        assert not matches_word_intent("sin salsa", "confirm")

    def test_ok_does_not_match_inside_product_name(self):
        assert not matches_word_intent("coke", "confirm")
        assert matches_word_intent("ok", "confirm")


class TestKeywordsFor:
    def test_all_languages_by_default(self):
        every = keywords_for("confirm")
        assert "sí" in every
        assert "yes" in every
        assert "sim" in every

    def test_single_language(self):
        only_en = keywords_for("confirm", "en")
        assert "yes" in only_en
        assert "sí" not in only_en

    def test_unknown_intent_returns_empty(self):
        assert keywords_for("not_an_intent") == []
