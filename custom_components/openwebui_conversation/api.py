"""OpenWebUI API Client."""
from __future__ import annotations
import asyncio
import socket
import uuid
import time
import aiohttp
import async_timeout
from .exceptions import ApiClientError, ApiCommError, ApiJsonError, ApiTimeoutError

class OpenWebUIApiClient:
    """OpenWebUI API Client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int,
        verify_ssl: bool,
        session: aiohttp.ClientSession,
    ) -> None:
        """Sample API Client."""
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.timeout = timeout
        self._verify_ssl = verify_ssl
        self._session = session

    def _auth_headers(self) -> dict:
        """Return standard auth headers."""
        return {
            "Content-type": "application/json; charset=UTF-8",
            "Authorization": f"Bearer {self._api_key}",
        }

    async def async_get_heartbeat(self) -> bool:
        """Get heartbeat from the API."""
        response = await self._api_wrapper(method="get", url=f"{self._base_url}/health")
        return response["status"] == True

    async def async_get_models(self) -> any:
        """Get models from the API."""
        return await self._api_wrapper(
            method="get",
            url=f"{self._base_url}/api/models",
            headers=self._auth_headers(),
        )

    async def async_generate(
        self,
        data: dict | None = None,
    ) -> any:
        """Generate a completion from the API (legacy, kept for compatibility)."""
        return await self._api_wrapper(
            method="post",
            url=f"{self._base_url}/api/chat/completions",
            data=data,
            headers=self._auth_headers(),
        )

    async def async_create_chat(
        self,
        model: str,
        prompt: str,
        user_msg_id: str,
        assistant_msg_id: str,
    ) -> str:
        """Create a chat record in OWUI and return the chat_id."""
        now = int(time.time())
        payload = {
            "chat": {
                "title": "HA Voice",
                "models": [model],
                "history": {
                    "currentId": assistant_msg_id,
                    "messages": {
                        user_msg_id: {
                            "id": user_msg_id,
                            "role": "user",
                            "content": prompt,
                            "timestamp": now,
                            "models": [model],
                            "childrenIds": [assistant_msg_id],
                        },
                        assistant_msg_id: {
                            "id": assistant_msg_id,
                            "role": "assistant",
                            "content": "",
                            "parentId": user_msg_id,
                            "childrenIds": [],
                            "model": model,
                            "modelName": model,
                            "modelIdx": 0,
                            "done": False,
                            "timestamp": now + 1,
                        },
                    },
                },
            }
        }
        result = await self._api_wrapper(
            method="post",
            url=f"{self._base_url}/api/v1/chats/new",
            data=payload,
            headers=self._auth_headers(),
        )
        return result["id"]

    async def async_fire_completion(
        self,
        model: str,
        messages: list,
        chat_id: str,
        assistant_msg_id: str,
        tool_ids: list | None = None,
        features: dict | None = None,
    ) -> None:
        """Fire the Path A completion. OWUI runs tools server-side; response is empty."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "chat_id": chat_id,
            "id": assistant_msg_id,
            "session_id": f"ha-{uuid.uuid4()}",
            "features": features or {
                "web_search": False,
                "code_interpreter": False,
                "image_generation": False,
                "memory": False,
            },
            "background_tasks": {
                "title_generation": False,
                "tags_generation": False,
                "follow_up_generation": False,
            },
        }
        if tool_ids:
            payload["tool_ids"] = tool_ids

        await self._api_wrapper(
            method="post",
            url=f"{self._base_url}/api/chat/completions",
            data=payload,
            headers=self._auth_headers(),
        )

    async def async_poll_tasks(
        self,
        chat_id: str,
        poll_interval: float = 2.0,
    ) -> None:
        """Poll until OWUI finishes all tasks for this chat."""
        deadline = asyncio.get_event_loop().time() + self.timeout
        while asyncio.get_event_loop().time() < deadline:
            result = await self._api_wrapper(
                method="get",
                url=f"{self._base_url}/api/tasks/chat/{chat_id}",
                headers=self._auth_headers(),
            )
            task_ids = result.get("task_ids", [])
            if not task_ids:
                return
            await asyncio.sleep(poll_interval)
        raise ApiTimeoutError(f"chat {chat_id} did not finish within timeout")

    async def async_read_result(
        self,
        chat_id: str,
        assistant_msg_id: str,
    ) -> str:
        """Read the finished assistant message content from the chat record."""
        result = await self._api_wrapper(
            method="get",
            url=f"{self._base_url}/api/v1/chats/{chat_id}",
            headers=self._auth_headers(),
        )
        messages = result["chat"]["history"]["messages"]
        return messages[assistant_msg_id]["content"]

    async def async_delete_chat(self, chat_id: str) -> None:
        """Delete the chat record from OWUI."""
        await self._api_wrapper(
            method="delete",
            url=f"{self._base_url}/api/v1/chats/{chat_id}",
            headers=self._auth_headers(),
            decode_json=False,
        )

    async def _api_wrapper(
        self,
        method: str,
        url: str,
        data: dict | None = None,
        headers: dict | None = None,
        decode_json: bool = True,
    ) -> any:
        """Get information from the API."""
        try:
            async with async_timeout.timeout(self.timeout):
                response = await self._session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    verify_ssl=self._verify_ssl,
                )
                if response.status == 404 and decode_json:
                    try:
                        json = await response.json()
                        raise ApiJsonError(json.get("error", json))
                    except Exception:
                        pass
                if response.status >= 400:
                    error_text = ""
                    try:
                        error_text = await response.text()
                    except Exception:
                        error_text = "<could not read body>"
                    raise ApiCommError(
                        f"HTTP {response.status} from {url}: {error_text[:500] if error_text else 'no body'}"
                    )
                if decode_json:
                    return await response.json()
                return await response.text()
        except ApiJsonError as e:
            raise e
        except asyncio.TimeoutError as e:
            raise ApiTimeoutError("timeout while talking to the server") from e
        except (aiohttp.ClientError, socket.gaierror) as e:
            raise ApiCommError(f"communication error: {e}") from e
        except Exception as e:  # pylint: disable=broad-except
            raise ApiClientError(f"unexpected error: {e}") from e
