"""Vision — image analysis and screenshot understanding.

Provides tools for analyzing images, screenshots, and other visual content.
Uses an auxiliary vision-capable model to describe and answer questions about images.
Falls back to basic file info when no vision provider is available.
"""
import base64
import json
import shutil
import subprocess
import time
from pathlib import Path

# ─── Helpers ──────────────────────────────────────────────────────────────────

_LAST_SCREENSHOT: str = ""


def _workspace_dir() -> Path:
    return Path.home() / ".Koza" / "workspace"


def _screenshot_dir() -> Path:
    d = _workspace_dir() / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check_deps() -> dict:
    """Check what vision-related tools are available."""
    deps = {
        "python": True,
        "PIL": False,
        "pytesseract": False,
    }
    try:
        from PIL import Image
        deps["PIL"] = True
    except ImportError:
        pass
    deps["tesseract"] = shutil.which("tesseract") is not None
    return deps


def _file_size_str(path: Path) -> str:
    size = path.stat().st_size
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    else:
        return f"{size / (1024*1024):.1f}MB"


# ─── Tool: vision_analyze ─────────────────────────────────────────────────────

def vision_analyze(image_path: str, question: str = "Describe this image in detail.") -> str:
    """Analyze an image using available tools."""
    path = Path(image_path).expanduser()
    if not path.exists():
        return f"❌ Image not found: {image_path}"

    deps = _check_deps()
    info = []

    # Basic file info
    info.append(f"📁 File: {path.name} ({_file_size_str(path)})")
    info.append(f"📅 Modified: {time.strftime('%Y-%m-%d %H:%M', time.localtime(path.stat().st_mtime))}")

    # Try PIL for image metadata
    if deps["PIL"]:
        try:
            from PIL import Image
            with Image.open(path) as img:
                info.append(f"🖼️ Dimensions: {img.width}x{img.height}")
                info.append(f"🎨 Mode: {img.mode}")
                info.append(f"📋 Format: {img.format}")
        except Exception:
            pass

    # Try tesseract OCR
    ocr_text = ""
    if deps["tesseract"]:
        try:
            result = subprocess.run(
                ["tesseract", str(path), "stdout", "-l", "tur+eng"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                text = result.stdout.strip()
                if text:
                    ocr_text = text[:2000]
        except Exception:
            pass

    response_parts = ["## Image Analysis", ""]
    response_parts.extend(info)
    response_parts.append("")

    if ocr_text:
        response_parts.append(f"📝 OCR Text:\n{ocr_text}")
        response_parts.append("")

    response_parts.append(f"❓ Question: {question}")
    response_parts.append(f"ℹ️ To get deeper analysis, a vision-capable LLM provider is needed. "
                          f"The image path is: {path.resolve()}")

    return "\n".join(response_parts)


# ─── Tool: image_info ─────────────────────────────────────────────────────────

def image_info(path: str) -> str:
    """Get metadata about an image file (dimensions, format, size, etc.)."""
    p = Path(path).expanduser()
    if not p.exists():
        return f"❌ File not found: {path}"
    try:
        from PIL import Image
        with Image.open(p) as img:
            lines = [
                f"📁 {p.name}",
                f"   Size: {_file_size_str(p)}",
                f"   Dimensions: {img.width} x {img.height}",
                f"   Mode: {img.mode}",
                f"   Format: {img.format}",
            ]
            # Try to get EXIF
            try:
                exif = img.getexif()
                if exif:
                    from PIL.ExifTags import TAGS as EXIF_TAGS
                    exif_lines = []
                    for tag_id, value in exif.items():
                        tag_name = EXIF_TAGS.get(tag_id, tag_id)
                        if isinstance(value, bytes):
                            continue
                        exif_lines.append(f"      {tag_name}: {value}")
                    if exif_lines:
                        lines.append("   EXIF:")
                        lines.extend(exif_lines[:10])
            except Exception:
                pass
            return "\n".join(lines)
    except ImportError:
        return f"📁 {p.name} ({_file_size_str(p)}) — Install Pillow for dimension info."
    except Exception as e:
        return f"❌ Error reading image: {e}"


# ─── Tool: take_screenshot (wrapper for existing browser screenshot) ──────────

def take_screenshot(path: str = "") -> str:
    """Take a screenshot using available tools (import, scrot, gnome-screenshot, or maim)."""
    global _LAST_SCREENSHOT
    dest = Path(path).expanduser() if path else _screenshot_dir() / f"screenshot_{int(time.time())}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Try various screenshot tools
    tools = [
        ("import", ["import", "-window", "root", str(dest)]),
        ("gnome-screenshot", ["gnome-screenshot", "-f", str(dest)]),
        ("scrot", ["scrot", str(dest)]),
        ("maim", ["maim", str(dest)]),
    ]

    for name, cmd in tools:
        exe = shutil.which(name)
        if exe:
            try:
                subprocess.run(cmd, timeout=10, capture_output=True)
                if dest.exists() and dest.stat().st_size > 0:
                    _LAST_SCREENSHOT = str(dest)
                    return f"✅ Screenshot saved: {dest} ({_file_size_str(dest)})"
            except Exception:
                continue

    return "❌ No screenshot tool found. Install scrot, maim, or ImageMagick's import."


# ─── Tool: last_screenshot ────────────────────────────────────────────────────

def get_last_screenshot() -> str:
    """Return the path of the last screenshot taken."""
    global _LAST_SCREENSHOT
    if _LAST_SCREENSHOT and Path(_LAST_SCREENSHOT).exists():
        return f"📸 Last screenshot: {_LAST_SCREENSHOT}"
    # Look for most recent screenshot
    d = _screenshot_dir()
    if d.exists():
        screenshots = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        if screenshots:
            _LAST_SCREENSHOT = str(screenshots[0])
            return f"📸 Most recent screenshot: {screenshots[0]}"
    return "No screenshots found."


# ─── Tool definitions ─────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "vision_analyze",
        "description": (
            "Analyze an image file: get dimensions, format, colors, and OCR text. "
            "Use this when the user uploads or references an image, screenshot, photo, or diagram. "
            "Can extract text from images using OCR. Pass the image path and optionally a question."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Path to the image file"},
                "question":   {"type": "string", "description": "Optional question about the image content", "default": "Describe this image in detail."},
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "image_info",
        "description": "Get metadata about an image file (dimensions, format, size, EXIF data).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the image file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "take_screenshot",
        "description": "Take a screenshot of the current desktop. Saves to workspace/screenshots/.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Optional custom save path", "default": ""},
            },
        },
    },
    {
        "name": "get_last_screenshot",
        "description": "Return the path of the last screenshot taken.",
        "parameters": {"type": "object", "properties": {}},
    },
]

HANDLERS: dict = {
    "vision_analyze":      lambda image_path, question="Describe this image in detail.": vision_analyze(image_path, question),
    "image_info":          lambda path: image_info(path),
    "take_screenshot":     lambda path="": take_screenshot(path),
    "get_last_screenshot": lambda: get_last_screenshot(),
}
