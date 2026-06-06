import json
from pathlib import Path

from config import load_config, save_config
from providers.factory import get_provider
from core import Agent

CORE_SKILLS_METADATA = [
    {"id": "browser_control", "name": "Browser Control", "desc": "Playwright-based automated browser tasks and navigation.", "category": "web"},
    {"id": "code_runner", "name": "Code Runner", "desc": "Execute Python, Node.js, and script codes locally.", "category": "development"},
    {"id": "kanban", "name": "Kanban Board", "desc": "Manage tasks on the native Todo, In Progress, Done Kanban board.", "category": "productivity"},
    {"id": "cron", "name": "Scheduler (Cron)", "desc": "Schedule one-shot timers or recurring cron tasks.", "category": "productivity"},
    {"id": "creative", "name": "Creative Tools", "desc": "Generate architectural diagrams, ASCII art, and creative text.", "category": "creative"},
    {"id": "datascience", "name": "Data Science", "desc": "Matplotlib plotting and Pandas query helpers.", "category": "analysis"},
    {"id": "devops", "name": "DevOps Tools", "desc": "Docker execution, Git commands, and Webhook listeners.", "category": "development"},
    {"id": "email_skill", "name": "Email Client", "desc": "Send and read emails using SMTP/IMAP configurations.", "category": "communication"},
    {"id": "finance", "name": "Finance & Markets", "desc": "Crypto prices, stock info, and portfolio summaries.", "category": "analysis"},
    {"id": "gaming", "name": "Gaming", "desc": "Play chess and other games in chat.", "category": "creative"},
    {"id": "github_skill", "name": "GitHub Client", "desc": "GitHub repository searches, issue creation, and pull requests.", "category": "development"},
    {"id": "mcp_skill", "name": "Model Context Protocol", "desc": "Extend capability via Model Context Protocol (MCP) servers.", "category": "development"},
    {"id": "media", "name": "Media Tools", "desc": "Generate and edit images and video files.", "category": "creative"},
    {"id": "mlops", "name": "MLOps", "desc": "Hugging Face model downloads and ML tools.", "category": "development"},
    {"id": "productivity", "name": "Productivity Suite", "desc": "Manage calendar, alarms, PDFs, and document conversion.", "category": "productivity"},
    {"id": "research", "name": "Academic Research", "desc": "Search scientific publications on arXiv, PubMed, and OpenAlex.", "category": "analysis"},
    {"id": "security", "name": "Security & Network", "desc": "Network port scans, WHOIS lookups, and SSL checks.", "category": "system"},
    {"id": "smarthome", "name": "Smart Home", "desc": "Control devices integrated with Home Assistant.", "category": "system"},
    {"id": "social", "name": "Social Media", "desc": "Search and post to Twitter, Mastodon, Bluesky, LinkedIn, and Threads.", "category": "communication"},
    {"id": "messaging", "name": "Messaging Channels", "desc": "Send messages to Telegram, Discord, or Twilio SMS/WhatsApp.", "category": "communication"},
    {"id": "sync", "name": "Multi-host Sync", "desc": "Synchronize notes and memory data across multiple hosts.", "category": "system"},
    {"id": "vision", "name": "Computer Vision", "desc": "Analyze images, run local OCR, and detect objects.", "category": "analysis"},
    {"id": "delegation", "name": "Agent Delegation", "desc": "Define and spawn sub-agents to execute tasks in parallel.", "category": "development"},
    {"id": "repo_manager", "name": "Repo Manager", "desc": "Search, read, and manage repository files and structures.", "category": "development"},
]

class SkillsMixin:
    def reload_agent(self):
        """Re-instantiate the agent to apply new tools, models, or configurations."""
        try:
            self.cfg = load_config()
            provider = get_provider(self.cfg)
            self.agent = Agent(provider, db_path=self.db_path, cfg=self.cfg, channel="gui")
            self.agent.permission_callback = self._gui_permission_callback
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_core_skills(self):
        """Return list of optional core skills with their active state."""
        try:
            self.cfg = load_config()
            disabled = self.cfg.get("disabled_skills", [])
            skills = []
            for s in CORE_SKILLS_METADATA:
                skills.append({
                    "id": s["id"],
                    "name": s["name"],
                    "desc": s["desc"],
                    "category": s["category"],
                    "enabled": s["id"] not in disabled
                })
            return {"status": "success", "data": skills}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def toggle_core_skill(self, skill_id, enable):
        """Enable or disable a core built-in skill."""
        try:
            self.cfg = load_config()
            disabled = self.cfg.get("disabled_skills", [])
            if not enable:
                if skill_id not in disabled:
                    disabled.append(skill_id)
            else:
                if skill_id in disabled:
                    disabled.remove(skill_id)
            self.cfg["disabled_skills"] = disabled
            save_config(self.cfg)
            
            # Rebuild registry and reload agent to apply changes immediately
            from tools.registry import rebuild_registry
            rebuild_registry()
            self.reload_agent()
            
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_plugins(self):
        """Return list of installed plugins with their active state."""
        try:
            from skills.plugin_loader import discover_plugins
            plugins = discover_plugins()
            return {"status": "success", "data": plugins}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def toggle_plugin(self, plugin_name, enable):
        """Enable or disable an external plugin."""
        try:
            from skills.plugin_loader import plugin_enable, plugin_disable
            if enable:
                plugin_enable(plugin_name)
            else:
                plugin_disable(plugin_name)
            
            # Rebuild registry and reload agent to apply changes immediately
            from tools.registry import rebuild_registry
            rebuild_registry()
            self.reload_agent()
            
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_skill_templates(self):
        """Return list of saved skill templates."""
        try:
            skills_dir = Path.home() / ".Koza" / "skill_templates"
            skills_dir.mkdir(parents=True, exist_ok=True)
            
            templates = []
            for path in sorted(skills_dir.glob("*.json")):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    templates.append({
                        "name": data.get("name", path.stem),
                        "desc": data.get("description", ""),
                        "steps": data.get("steps", []),
                        "tags": data.get("tags", []),
                        "use_count": data.get("use_count", 0)
                    })
                except Exception:
                    continue
            return {"status": "success", "data": templates}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_skill_template(self, name):
        """Delete a saved skill template."""
        try:
            from skills.skill_ecosystem import skill_delete
            res = skill_delete(name)
            return {"status": "success", "message": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def create_plugin(self, name, description, author):
        """Create a new external plugin."""
        try:
            from skills.plugin_loader import plugin_create
            res = plugin_create(name, description, author)
            if res.startswith("✅"):
                return {"status": "success", "message": res}
            else:
                return {"status": "error", "message": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}
