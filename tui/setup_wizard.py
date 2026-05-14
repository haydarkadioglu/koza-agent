"""Setup Wizard — Textual TUI for first-time configuration."""
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Label, Input, Select, Button, Static
from textual.containers import Container, Vertical, Horizontal
from textual.screen import Screen
from textual import on

from config import save_config, default_config

PROVIDERS = ["ollama", "openai", "anthropic", "deepseek", "gemini"]

PROVIDER_MODELS = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"],
    "deepseek": ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"],
    "gemini": ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"],
    "ollama": ["llama3", "mistral", "codellama", "phi3"],
}

NEEDS_KEY = {"openai", "anthropic", "deepseek", "gemini"}


class WizardScreen(Screen):
    CSS = """
    Screen { align: center middle; }
    #wizard { width: 70; background: $surface; border: round $accent; padding: 2 4; }
    #title { text-align: center; color: $accent; text-style: bold; margin-bottom: 1; }
    #subtitle { text-align: center; color: $text-muted; margin-bottom: 2; }
    Label { margin-top: 1; color: $text; }
    Input { margin-top: 0; }
    Select { margin-top: 0; }
    #actions { margin-top: 2; align: center middle; }
    Button { margin: 0 1; }
    #status { text-align: center; color: $warning; margin-top: 1; height: 1; }
    """

    def compose(self) -> ComposeResult:
        with Container(id="wizard"):
            yield Static("🪽  H E R M E S  A G E N T", id="title")
            yield Static("First-time setup — configure your LLM provider", id="subtitle")

            yield Label("LLM Provider")
            yield Select(
                [(p.capitalize(), p) for p in PROVIDERS],
                id="provider_select",
                value="ollama",
            )

            yield Label("Model")
            yield Input(placeholder="e.g. llama3, gpt-4o ...", id="model_input")

            yield Label("API Key (leave blank for Ollama / ADC auth)")
            yield Input(placeholder="sk-...", id="api_key_input", password=True)

            yield Label("Ollama Base URL (only for Ollama)")
            yield Input(value="http://localhost:11434", id="ollama_url_input")

            yield Static("", id="status")

            with Horizontal(id="actions"):
                yield Button("Save & Start", variant="primary", id="save_btn")
                yield Button("Quit", variant="error", id="quit_btn")

    @on(Select.Changed, "#provider_select")
    def provider_changed(self, event: Select.Changed) -> None:
        provider = str(event.value)
        models = PROVIDER_MODELS.get(provider, [])
        model_input = self.query_one("#model_input", Input)
        if models:
            model_input.placeholder = f"e.g. {models[0]}"
        ollama_input = self.query_one("#ollama_url_input", Input)
        ollama_input.disabled = provider != "ollama"

    @on(Button.Pressed, "#save_btn")
    def save_pressed(self) -> None:
        provider = str(self.query_one("#provider_select", Select).value)
        model = self.query_one("#model_input", Input).value.strip()
        api_key = self.query_one("#api_key_input", Input).value.strip()
        ollama_url = self.query_one("#ollama_url_input", Input).value.strip()

        if provider in NEEDS_KEY and not api_key:
            self.query_one("#status", Static).update(f"⚠ API key required for {provider}")
            return

        cfg = default_config()
        cfg["provider"] = provider
        cfg["model"] = model or PROVIDER_MODELS.get(provider, [""])[0]
        if api_key:
            cfg["providers"][provider]["api_key"] = api_key
        if provider == "ollama":
            cfg["providers"]["ollama"]["base_url"] = ollama_url

        save_config(cfg)
        self.app.exit(cfg)

    @on(Button.Pressed, "#quit_btn")
    def quit_pressed(self) -> None:
        self.app.exit(None)


class SetupWizard(App):
    TITLE = "Koza Agent — Setup"

    def on_mount(self) -> None:
        self.push_screen(WizardScreen())
