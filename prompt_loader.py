"""Prompt Loader — harici .md dosyalarından prompt yükleme ve cache.

Singleton pattern ile çalışır. Dosyalar UTF-8 olarak okunur,
mtime-based cache invalidation ile performans garanti edilir.
Thread-safe: tüm cache erişimleri threading.Lock ile korunur.
"""

import os
import threading
from pathlib import Path
from typing import Optional


class PromptLoader:
    """Singleton prompt loader with file-based caching and mtime invalidation."""

    _instance: Optional["PromptLoader"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "PromptLoader":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._prompts_dir = Path(__file__).parent / "prompts"
            instance._cache: dict[str, tuple[str, float]] = {}
            instance._cache_lock = threading.Lock()
            cls._instance = instance
        return cls._instance

    def load(self, relative_path: str) -> str:
        """Load a prompt file with caching and mtime-based invalidation.

        Args:
            relative_path: Path relative to the prompts/ directory.

        Returns:
            The prompt content with leading/trailing whitespace stripped.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file is empty or contains only whitespace.
        """
        full_path = self._prompts_dir / relative_path

        if not full_path.exists():
            raise FileNotFoundError(
                f"Prompt file not found: {full_path}"
            )

        current_mtime = os.path.getmtime(full_path)

        with self._cache_lock:
            if relative_path in self._cache:
                cached_content, cached_mtime = self._cache[relative_path]
                if cached_mtime == current_mtime:
                    return cached_content

        # Read file outside the lock to avoid holding it during I/O
        content = full_path.read_text(encoding="utf-8")
        content = content.strip()

        if not content:
            raise ValueError(
                f"Prompt file is empty or contains only whitespace: {full_path}"
            )

        with self._cache_lock:
            self._cache[relative_path] = (content, current_mtime)

        return content

    def load_section(self, name: str) -> str:
        """Load a section prompt by name.

        Args:
            name: Section name (without extension), e.g. "workspace".

        Returns:
            The section prompt content.

        Raises:
            FileNotFoundError: If the section file does not exist.
            ValueError: If the section file is empty.
        """
        return self.load(f"sections/{name}.md")

    def load_persona(self, name: str) -> str:
        """Load a persona prompt by name.

        Args:
            name: Persona name (without extension), e.g. "team_lead".

        Returns:
            The persona prompt content.

        Raises:
            FileNotFoundError: If the persona file does not exist.
            ValueError: If the persona file is empty.
        """
        return self.load(f"personas/{name}.md")

    def load_channel(self, name: str) -> Optional[str]:
        """Load a channel prompt by name. Returns None if file doesn't exist.

        Unlike other load methods, this does NOT raise FileNotFoundError
        for missing files — channels are optional.

        Args:
            name: Channel name (without extension), e.g. "telegram".

        Returns:
            The channel prompt content, or None if the file doesn't exist.

        Raises:
            ValueError: If the channel file exists but is empty.
        """
        try:
            return self.load(f"channels/{name}.md")
        except FileNotFoundError:
            return None

    def list_sections(self) -> list[str]:
        """List available section names from the prompts/sections/ directory.

        Returns:
            List of section names (without .md extension), sorted alphabetically.
        """
        sections_dir = self._prompts_dir / "sections"
        if not sections_dir.exists():
            return []

        return sorted(
            f.stem for f in sections_dir.iterdir()
            if f.is_file() and f.suffix == ".md"
        )

    def invalidate(self, relative_path: str = None) -> None:
        """Invalidate cache entry or entire cache.

        Args:
            relative_path: If provided, invalidates only that entry.
                          If None, clears the entire cache.
        """
        with self._cache_lock:
            if relative_path is None:
                self._cache.clear()
            else:
                self._cache.pop(relative_path, None)
