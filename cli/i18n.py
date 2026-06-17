import locale
import os
import threading
from pathlib import Path
from config import load_config

_active_lang = None
_catalog_cache = {}
_catalog_lock = threading.Lock()

_LANG_NORMALIZATION = {
    "tr": "tr", "turkish": "tr", "türkçe": "tr", "tur": "tr",
    "en": "en", "english": "en", "eng": "en",
}


def normalize_language(lang: str) -> str:
    if not lang:
        return "en"
    lang_clean = lang.strip().lower().replace("_", "-")
    if lang_clean in _LANG_NORMALIZATION:
        return _LANG_NORMALIZATION[lang_clean]
    base = lang_clean.split("-")[0]
    if base in _LANG_NORMALIZATION:
        return _LANG_NORMALIZATION[base]
    return base


def get_language() -> str:
    # Always enforce English for the interface
    return "en"


def set_language(lang: str) -> None:
    # No-op to enforce English-only interface
    pass


def reset_language_cache() -> None:
    global _active_lang, _catalog_cache
    with _catalog_lock:
        _catalog_cache.clear()



def _load_catalog(lang: str) -> dict[str, str]:
    """Load translation catalog from locales/<lang>.yaml dynamically."""
    global _catalog_cache
    with _catalog_lock:
        if lang in _catalog_cache:
            return _catalog_cache[lang]

    locales_dir = Path(__file__).parent.parent / "locales"
    path = locales_dir / f"{lang}.yaml"
    if not path.is_file():
        with _catalog_lock:
            _catalog_cache[lang] = {}
        return {}

    try:
        import yaml
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        raw = {}

    with _catalog_lock:
        _catalog_cache[lang] = raw
    return raw


def _T(text: str) -> str:
    lang = get_language()
    if lang == "en":
        # Translate Turkish hardcoded strings to English
        english_catalog = _load_catalog("en")
        for k, v in english_catalog.items():
            if k in text:
                text = text.replace(k, v)
        return text
        
    translations_dict = _load_catalog(lang)
    if text in translations_dict:
        return translations_dict[text]
        
    # Pattern matching for file download string
    if lang == "tr":
        if text.startswith("[File downloaded:"):
            return text.replace("[File downloaded:", "[Dosya indirildi:")
            
    # Loose strip matching (ignores prefixes, emojis, punctuation)
    stripped = text.strip(" \n\r\t✓✗ℹ⏳💾🐝✨🦎.")
    if stripped in translations_dict:
        prefix = text[:text.find(stripped)]
        suffix = text[text.find(stripped) + len(stripped):]
        return prefix + translations_dict[stripped] + suffix
        
    for k, v in translations_dict.items():
        if k in text:
            return text.replace(k, v)
            
    return text

