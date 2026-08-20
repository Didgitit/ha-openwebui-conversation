"""Constants for openwebui_conversation."""
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

NAME = "OpenWebUI Conversation"
DOMAIN = "openwebui_conversation"

MENU_OPTIONS = ["general_config", "model_config", "tools_config", "features_config"]

CONF_SERVICE_NAME = "service_name"
CONF_BASE_URL = "base_url"
CONF_API_KEY = "api_key"
CONF_TIMEOUT = "timeout"
CONF_MODEL = "chat_model"
CONF_TOOL_IDS = "tool_ids"
CONF_LANGUAGE_CODE = "lang_code"
CONF_WEB_SEARCH = "web_search_enabled"
CONF_CODE_INTERPRETER = "code_interpreter_enabled"
CONF_IMAGE_GENERATION = "image_generation_enabled"
CONF_MEMORY = "memory_enabled"
CONF_STRIP_MARKDOWN = "strip_markdown"
CONF_VERIFY_SSL = "verify_ssl"
CONF_KEEP_CHAT_HISTORY = "keep_chat_history"

DEFAULT_SERVICE_NAME = "OpenWebUI"
DEFAULT_BASE_URL = "http://openwebui.homeassistant.local"
DEFAULT_TIMEOUT = 60
DEFAULT_MODEL = "llama2:latest"
DEFAULT_TOOL_IDS: list = []
DEFAULT_LANGUAGE_CODE = "en"
DEFAULT_WEB_SEARCH = False
DEFAULT_CODE_INTERPRETER = False
DEFAULT_IMAGE_GENERATION = False
DEFAULT_MEMORY = False
DEFAULT_STRIP_MARKDOWN = False
DEFAULT_VERIFY_SSL = True
DEFAULT_KEEP_CHAT_HISTORY = False
