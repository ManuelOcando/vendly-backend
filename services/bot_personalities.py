"""
Named bot personalities, so a tenant can pick how their bot sounds without
configuring anything.

Three levels, cheapest first:

1. A preset. The seller taps a number during onboarding and is done. Presets are
   defined here rather than in the database because they are product decisions,
   not tenant data - adding a fifth one should be a code review, not a migration.
2. No choice at all. `bot_personality_preset` defaults to 'auto', which resolves
   from the tenant's industry: a restaurant sounds warm, a law office sounds
   formal. A tenant who skips the question still gets something sensible.
3. A free-form prompt in `tenants.bot_personality`, which overrides everything.
   Reserved for bespoke configuration done by hand; empty for almost everyone.

Each preset is a combination of the three knobs the providers already consume
(`services/llm/providers/*.py` read exactly `tone`, `use_emojis` and
`greeting_style`), and the defaults for those live in `config.py`.

Historical note: `_get_personality()` used to read `bot_personality` from
`whatsapp_configs`, where the column does not exist, and then json.loads() the
result. Even pointed at the right table it would have failed, because the column
holds prose and not JSON. Per-tenant personality had never worked.
"""
from typing import Any, Dict, Optional

from config import get_settings

# The value of tenants.bot_personality_preset that means "decide for me".
AUTO = "auto"

# Kept in sync with the CHECK constraint added by migration 020.
PRESETS: Dict[str, Dict[str, Any]] = {
    "calido": {
        "label": "Cálido y cercano",
        "tone": "amigable",
        "use_emojis": True,
        "greeting_style": "¡Hola! 👋 Qué bueno tenerte por acá. Bienvenido a {store_name}",
        "sample": "¡Hola! 👋 Qué bueno verte. ¿Te preparo algo rico hoy?",
    },
    "formal": {
        "label": "Formal y profesional",
        "tone": "formal",
        "use_emojis": False,
        "greeting_style": "Buenos días. Bienvenido a {store_name}, ¿en qué podemos ayudarle?",
        "sample": "Buenos días. ¿En qué puedo asistirle el día de hoy?",
    },
    "directo": {
        "label": "Breve y directo",
        "tone": "profesional",
        "use_emojis": False,
        "greeting_style": "Hola, bienvenido a {store_name}. ¿Qué necesitás?",
        "sample": "Hola. ¿Qué producto buscás?",
    },
    "divertido": {
        "label": "Divertido y relajado",
        "tone": "casual",
        "use_emojis": True,
        "greeting_style": "¡Ey! 🎉 Bienvenido a {store_name}, pasá que hay de todo",
        "sample": "¡Ey! 🎉 ¿Qué se te antoja hoy?",
    },
}

# tenants.type, as written by MultiTenantOrchestrator._apply_industry_template.
_PRESET_BY_INDUSTRY = {
    "restaurant": "calido",
    "retail": "directo",
    "services": "formal",
}

_FALLBACK_PRESET = "calido"

# The column default from migration 001. A tenant still holding exactly this
# string never chose a custom prompt, so it must not be treated as one.
DEFAULT_BOT_PERSONALITY_PROMPT = (
    "Eres un asistente de ventas amable y profesional. Ayudas a los clientes a "
    "encontrar lo que necesitan y completar sus compras."
)


def preset_names() -> list:
    """Preset keys in the order they are offered during onboarding."""
    return list(PRESETS)


def default_preset_for_industry(industry: Optional[str]) -> str:
    """Which preset an industry sounds like by default."""
    return _PRESET_BY_INDUSTRY.get((industry or "").lower(), _FALLBACK_PRESET)


def knobs_from_settings() -> Dict[str, Any]:
    """Last-resort personality, straight from configuration."""
    settings = get_settings()
    return {
        "tone": settings.BOT_DEFAULT_TONE,
        "use_emojis": settings.BOT_DEFAULT_EMOJIS,
        "greeting_style": settings.BOT_DEFAULT_GREETING,
    }


def knobs_for_preset(name: Optional[str]) -> Dict[str, Any]:
    """The three provider knobs for a preset, or the settings defaults."""
    preset = PRESETS.get(name or "")
    if not preset:
        return knobs_from_settings()
    return {
        "tone": preset["tone"],
        "use_emojis": preset["use_emojis"],
        "greeting_style": preset["greeting_style"],
    }


def has_custom_prompt(bot_personality: Optional[str]) -> bool:
    """True when a tenant has a hand-written prompt, not the column default.

    Strips before testing emptiness: a whitespace-only column is not a prompt,
    but it is truthy.
    """
    if not bot_personality:
        return False
    stripped = bot_personality.strip()
    return bool(stripped) and stripped != DEFAULT_BOT_PERSONALITY_PROMPT


def resolve_personality(tenant: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn a tenants row into the personality dict the providers expect.

    Always returns the three knobs, so a provider that ignores `custom_prompt`
    still behaves. Precedence: hand-written prompt, then chosen preset, then the
    industry default, then configuration.
    """
    tenant = tenant or {}

    preset_name = tenant.get("bot_personality_preset") or AUTO
    if preset_name == AUTO or preset_name not in PRESETS:
        preset_name = default_preset_for_industry(tenant.get("type"))

    personality = knobs_for_preset(preset_name)
    personality["preset"] = preset_name

    custom_prompt = tenant.get("bot_personality")
    if has_custom_prompt(custom_prompt):
        personality["custom_prompt"] = custom_prompt.strip()

    return personality
