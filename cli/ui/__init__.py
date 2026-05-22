"""cli.ui package — backward-compatible re-export of all UI symbols."""
from ._colors import _ANSI, _C, _hr, _section
from ._io import (
    _config_path, _print_error, _select_menu, _prompt,
    _extract_gemini_cookies, _prompt_secret,
)
from ._spinner import (
    _spinner_active_check, _spinner_set, _spinner_start, _spinner_stop,
)
from ._render import _render_md
from ._banner import (
    _LOGO, _TOOL_CATEGORIES, _get_version, _print_banner, _print_inline_help,
)
from ._layout import ChatLayout
from ._stream_renderer import StreamRenderer

__all__ = [
    "_ANSI", "_C", "_hr", "_section",
    "_config_path", "_print_error", "_select_menu", "_prompt",
    "_extract_gemini_cookies", "_prompt_secret",
    "_spinner_active_check", "_spinner_set", "_spinner_start", "_spinner_stop",
    "_render_md",
    "_LOGO", "_TOOL_CATEGORIES", "_get_version", "_print_banner", "_print_inline_help",
    "ChatLayout",
    "StreamRenderer",
]
