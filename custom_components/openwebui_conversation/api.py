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
    ) ->
