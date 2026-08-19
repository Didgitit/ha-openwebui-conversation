"""OpenWebUI conversation agent."""

from __future__ import annotations

import uuid
from typing import Literal

from hassil import recognize
from hassil.intents import Intents

from homeassistant.components import conversation
from homeassistant.components.conversation import async_get_chat_log
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
)
from homeassistant.helpers import intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import ulid

from markdown_it import MarkdownIt
from mdit_plain.renderer import RendererPlain

from .api import OpenWebUIApiClient
from .const import (
    LOGGER,
    DO_SEARCH_INTENT,
    CONF_BASE_URL,
    CONF_API_KEY,
    CONF_TIMEOUT,
    CONF_MODEL,
    CONF_TOOL_IDS,
    CONF_LANGUAGE_CODE,
    CONF_SEARCH_ENABLED,
    CONF_SEARCH_SENTENCES,
    CONF_SEARCH_RESULT_PREFIX,
    CONF_STRIP_MARKDOWN,
    CONF_VERIFY_SSL,
    DEFAULT_TIMEOUT,
    DEFAULT_MODEL,
    DEFAULT_TOOL_IDS,
    DEFAULT_LANGUAGE_CODE,
    DEFAULT_SEARCH_ENABLED,
    DEFAULT_SEARCH_SENTENCES,
    DEFAULT_SEARCH_RESULT_PREFIX,
    DEFAULT_STRIP_MARKDOWN,
    DEFAULT_VERIFY_SSL,
)
from .exceptions import ApiCommError, ApiJsonError, ApiTimeoutError
from .message import Message


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> bool:
    """Set up OpenWebUI Conversation Agent from a config entry."""
    agent = OpenWebUIAgent(hass, entry)
    async_add_entities([agent])
    return True


class OpenWebUIAgent(conversation.ConversationEntity):
    """OpenWebUI conversation agent."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self.timeout = entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        self.client = OpenWebUIApiClient(
            base_url=entry.data[CONF_BASE_URL],
            api_key=entry.data[CONF_API_KEY],
            timeout=entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            session=async_get_clientsession(hass),
            verify_ssl=entry.options.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        )
        self.history: dict[str, list[Message]] = {}
        self.search_enabled = entry.options.get(
            CONF_SEARCH_ENABLED, DEFAULT_SEARCH_ENABLED
        )
        self.search_sentences = [
            x
            for x in entry.options.get(
                CONF_SEARCH_SENTENCES, DEFAULT_SEARCH_SENTENCES
            ).splitlines()
            if x.strip()
        ]
        self.search_result_prefix = entry.options.get(
            CONF_SEARCH_RESULT_PREFIX, DEFAULT_SEARCH_RESULT_PREFIX
        )
        self.lang = entry.options.get(CONF_LANGUAGE_CODE, DEFAULT_LANGUAGE_CODE).strip()
        self._attr_name = entry.title
        self._attr_unique_id = entry.entry_id
        self.strip_markdown = entry.options.get(
            CONF_STRIP_MARKDOWN, DEFAULT_STRIP_MARKDOWN
        )
        self.markdown_parser = MarkdownIt(renderer_cls=RendererPlain)

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self.entry.async_on_unload(
            self.entry.add_update_listener(self._async_entry_update_listener)
        )

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from Home Assistant."""
        await super().async_will_remove_from_hass()

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process a sentence."""

        user_message = Message("user", user_input.text)
        prompt = user_message.message

        should_search = False

        if self.search_enabled and len(self.search_sentences):
            i = Intents.from_dict(
                {
                    "language": self.lang,
                    "settings": {"ignore_whitespace": True},
                    "intents": {
                        DO_SEARCH_INTENT: {
                            "data": [{"sentences": self.search_sentences}]
                        }
                    },
                    "lists": {"query": {"wildcard": True}},
                }
            )
            r = recognize(prompt, i)
            if r is not None:
                if (
                    r.intent.name == DO_SEARCH_INTENT
                    and r.entities.get("query", None) is not None
                ):
                    prompt = r.entities["query"].value
                    should_search = True

        conversation_result = None
        conversation_id = user_input.conversation_id or ulid.ulid()
        conversation_history: list[Message] = []

        with async_get_chat_log(self.hass, user_input) as chat_log:
            conversation_id = chat_log.conversation_id or user_input.conversation_id or ulid.ulid()

            for content in chat_log.content:
                if hasattr(content, "role") and hasattr(content, "content") and content.role in ("user", "assistant"):
                    conversation_history.append(Message(content.role, content.content))

            if conversation_history and conversation_history[-1].role == "user":
                conversation_history.pop()

            if len(conversation_history) == 0 and conversation_id in self.history:
                conversation_history = list(self.history[conversation_id])
                LOGGER.debug("Falling back to legacy self.history for conv %s (%d turns)", conversation_id, len(conversation_history))

            LOGGER.debug(
                "History for %s: %d previous from chat_log (raw %d), legacy %d",
                conversation_id,
                len(conversation_history),
                len(chat_log.content),
                len(self.history.get(conversation_id, [])),
            )

            try:
                response_data = await self.query(
                    prompt, conversation_history, should_search
                )
            except (ApiCommError, ApiJsonError, ApiTimeoutError) as err:
                LOGGER.error("Error generating prompt: %s (cause: %s)", err, err.__cause__)
                intent_response = intent.IntentResponse(language=user_input.language)
                intent_response.async_set_error(
                    intent.IntentResponseErrorCode.UNKNOWN,
                    f"Something went wrong, {err}",
                )
                conversation_result = conversation.ConversationResult(
                    response=intent_response, conversation_id=conversation_id
                )
            except HomeAssistantError as err:
                LOGGER.error("Something went wrong: %s", err)
                intent_response = intent.IntentResponse(language=user_input.language)
                intent_response.async_set_error(
                    intent.IntentResponseErrorCode.UNKNOWN,
                    "Something went wrong, please check the logs for more information.",
                )
                conversation_result = conversation.ConversationResult(
                    response=intent_response, conversation_id=conversation_id
                )
            else:
                if self.strip_markdown:
                    response_data = self.markdown_parser.render(response_data)
                if should_search:
                    response_data = f"{self.search_result_prefix} {response_data}"
                response_message = Message("assistant", response_data)

                conversation_history.append(user_message)
                conversation_history.append(response_message)
                self.history[conversation_id] = conversation_history

                try:
                    from homeassistant.components.conversation.chat_log import AssistantContent
                    chat_log.async_add_assistant_content(
                        AssistantContent(
                            agent_id=self.entity_id,
                            content=response_data,
                        )
                    )
                except Exception as err:
                    LOGGER.error("Failed to add assistant turn to chat_log (history may not persist): %s", err)

                intent_response = intent.IntentResponse(language=user_input.language)
                intent_response.async_set_speech(response_data)
                conversation_result = conversation.ConversationResult(
                    response=intent_response, conversation_id=conversation_id
                )

        return conversation_result

    async def query(self, prompt: str, history: list[Message], search: bool) -> str:
        """Run a full Path A agentic loop via OWUI and return the finished response text."""
        model = self.entry.options.get(CONF_MODEL, DEFAULT_MODEL)
        tool_ids = self.entry.options.get(CONF_TOOL_IDS, DEFAULT_TOOL_IDS)

        message_list = [{"role": x.role, "content": x.message} for x in history]
        message_list.append({"role": "user", "content": prompt})

        LOGGER.debug("Sending %d messages to OpenWebUI (model=%s)", len(message_list), model)
        LOGGER.debug("Prompt for %s: %s", model, prompt)

        user_msg_id = str(uuid.uuid4())
        assistant_msg_id = str(uuid.uuid4())

        # Step 1: Create the chat record in OWUI
        chat_id = await self.client.async_create_chat(
            model=model,
            prompt=prompt,
            user_msg_id=user_msg_id,
            assistant_msg_id=assistant_msg_id,
        )
        LOGGER.debug("Created OWUI chat %s", chat_id)

        try:
            # Step 2: Fire the completion — OWUI runs tools server-side
            await self.client.async_fire_completion(
                model=model,
                messages=message_list,
                chat_id=chat_id,
                assistant_msg_id=assistant_msg_id,
                tool_ids=tool_ids,
                features={"web_search": search, "code_interpreter": False, "image_generation": False, "memory": False},
            )
            LOGGER.debug("Fired completion for chat %s, polling for result", chat_id)

            # Step 3: Poll until OWUI finishes all tool calls
            await self.client.async_poll_tasks(chat_id)
            LOGGER.debug("Tasks complete for chat %s, reading result", chat_id)

            # Step 4: Read the finished response
            response_data = await self.client.async_read_result(chat_id, assistant_msg_id)
            LOGGER.debug("Got response for chat %s: %s", chat_id, response_data[:100])

        finally:
            # Always clean up the chat record
            try:
                await self.client.async_delete_chat(chat_id)
                LOGGER.debug("Deleted OWUI chat %s", chat_id)
            except Exception as err:
                LOGGER.warning("Failed to delete OWUI chat %s: %s", chat_id, err)

        return response_data

    async def _async_entry_update_listener(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Handle options update."""
        await hass.config_entries.async_reload(entry.entry_id)
