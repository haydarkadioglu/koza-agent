from ui.bridge.base import BridgeBase
from ui.bridge.config import ConfigMixin
from ui.bridge.chat import ChatMixin
from ui.bridge.kanban import KanbanMixin
from ui.bridge.sessions import SessionMixin
from ui.bridge.skills import SkillsMixin
from ui.bridge.audio import AudioMixin

class KozaBridge(BridgeBase, ConfigMixin, ChatMixin, KanbanMixin, SessionMixin, SkillsMixin, AudioMixin):
    pass
