import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

import aiohttp
from aiohttp import web

from .config import RelayConfig, RelaySourceConfig


LOG = logging.getLogger("disraker")
RELAY_PATH = "/disraker/v1/status"
MAX_CLOCK_SKEW = 300


@dataclass(frozen=True)
class RelayStatus:
    relay_id: str
    printer_name: str
    status: Dict[str, Any]
    camera_data: Optional[bytes] = None
    camera_filename: str = "printer.jpg"


def _signature(secret: str, timestamp: str, nonce: str, body: bytes) -> str:
    message = ".".join((timestamp, nonce)).encode("ascii") + b"." + body
    return hmac.new(
        secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


class RelayPublisher:
    def __init__(self, config: RelayConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        if self.config.publish_url:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15.0))

    async def close(self):
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def publish(self, printer_name: str, status: Dict[str, Any],
                      camera_data: Optional[bytes] = None,
                      camera_filename: str = "printer.jpg") -> List[str]:
        if self._session is None:
            return []
        payload: Dict[str, Any] = {
            "relay_id": self.config.relay_id,
            "printer_name": printer_name,
            "status": status,
        }
        if camera_data is not None:
            payload["camera"] = base64.b64encode(camera_data).decode("ascii")
            payload["camera_filename"] = camera_filename
        body = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        headers = {
            "Content-Type": "application/json",
            "X-DisRaker-Id": self.config.relay_id,
            "X-DisRaker-Timestamp": timestamp,
            "X-DisRaker-Nonce": nonce,
            "X-DisRaker-Signature": _signature(
                self.config.secret, timestamp, nonce, body),
        }
        try:
            async with self._session.post(
                    self.config.publish_url, data=body,
                    headers=headers) as response:
                if response.status >= 400:
                    detail = (await response.text())[:300]
                    raise RuntimeError(
                        "relay returned HTTP {}: {}".format(
                            response.status, detail))
                response_body = await response.read()
                response_signature = response.headers.get(
                    "X-DisRaker-Response-Signature", "")
                expected_response = _signature(
                    self.config.secret, timestamp, nonce, response_body)
                if not hmac.compare_digest(
                        response_signature, expected_response):
                    raise RuntimeError("relay response signature is invalid")
                response_payload = json.loads(response_body.decode("utf-8"))
                if not isinstance(response_payload, dict):
                    raise RuntimeError("relay response is malformed")
                commands = response_payload.get("commands", [])
                if not isinstance(commands, list):
                    raise RuntimeError("relay commands are malformed")
                allowed = {"pause", "resume", "cancel"}
                return [str(item.get("action")) for item in commands
                        if isinstance(item, dict)
                        and item.get("action") in allowed]
        except (aiohttp.ClientError, TimeoutError, RuntimeError,
                UnicodeError, json.JSONDecodeError):
            LOG.warning("Unable to publish relay status", exc_info=True)
            return []


RelayCallback = Callable[[RelayStatus, RelaySourceConfig], Awaitable[None]]


class RelayServer:
    def __init__(self, config: RelayConfig, callback: RelayCallback):
        self.config = config
        self.callback = callback
        self._runner: Optional[web.AppRunner] = None
        self._seen_nonces: Dict[str, int] = {}
        self._commands: Dict[str, List[Dict[str, str]]] = {}

    def enqueue_command(self, relay_id: str, action: str):
        if action not in ("pause", "resume", "cancel"):
            raise ValueError("Unsupported relay command")
        queue = self._commands.setdefault(relay_id, [])
        queue.append({"id": secrets.token_hex(12), "action": action})
        del queue[:-10]

    async def start(self):
        if not self.config.listen_host:
            return
        app = web.Application(client_max_size=10 * 1024 * 1024)
        app.router.add_post(RELAY_PATH, self._receive)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(
            self._runner, self.config.listen_host,
            self.config.listen_port)
        await site.start()
        LOG.info("Relay listening on %s:%s%s",
                 self.config.listen_host, self.config.listen_port, RELAY_PATH)

    async def close(self):
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _receive(self, request: web.Request):
        relay_id = request.headers.get("X-DisRaker-Id", "")
        timestamp = request.headers.get("X-DisRaker-Timestamp", "")
        nonce = request.headers.get("X-DisRaker-Nonce", "")
        supplied_signature = request.headers.get(
            "X-DisRaker-Signature", "")
        source = self.config.sources.get(relay_id)
        if source is None:
            raise web.HTTPUnauthorized(text="Unknown relay source")
        if (not timestamp.isascii() or not timestamp.isdigit()
                or not nonce.isascii()):
            raise web.HTTPUnauthorized(text="Invalid relay headers")
        try:
            request_time = int(timestamp)
        except ValueError as exc:
            raise web.HTTPUnauthorized(text="Invalid relay timestamp") from exc
        if abs(int(time.time()) - request_time) > MAX_CLOCK_SKEW:
            raise web.HTTPUnauthorized(text="Expired relay request")
        if not nonce or len(nonce) > 128:
            raise web.HTTPUnauthorized(text="Invalid relay nonce")
        body = await request.read()
        expected = _signature(source.secret, timestamp, nonce, body)
        if not hmac.compare_digest(supplied_signature, expected):
            raise web.HTTPUnauthorized(text="Invalid relay signature")
        now = int(time.time())
        self._seen_nonces = {
            key: seen for key, seen in self._seen_nonces.items()
            if now - seen <= MAX_CLOCK_SKEW
        }
        nonce_key = "{}:{}".format(relay_id, nonce)
        if nonce_key in self._seen_nonces:
            raise web.HTTPUnauthorized(text="Relay request was replayed")
        self._seen_nonces[nonce_key] = now
        try:
            payload = json.loads(body.decode("utf-8"))
            status = payload["status"]
            if payload.get("relay_id") != relay_id:
                raise ValueError("relay ID does not match header")
            if not isinstance(status, dict):
                raise ValueError("status is not an object")
            camera_data = None
            if payload.get("camera"):
                camera_data = base64.b64decode(
                    payload["camera"], validate=True)
            camera_filename = str(
                payload.get("camera_filename") or "printer.jpg")
            camera_filename = camera_filename.replace(
                "\\", "/").split("/")[-1][:100]
            relay_status = RelayStatus(
                relay_id=relay_id,
                printer_name=str(payload.get("printer_name") or relay_id),
                status=status,
                camera_data=camera_data,
                camera_filename=camera_filename or "printer.jpg",
            )
        except (binascii.Error, KeyError, TypeError, ValueError,
                json.JSONDecodeError) as exc:
            raise web.HTTPBadRequest(text="Invalid relay payload") from exc
        await self.callback(relay_status, source)
        commands = self._commands.pop(relay_id, [])
        response_body = json.dumps(
            {"ok": True, "commands": commands},
            separators=(",", ":")).encode("utf-8")
        response_signature = _signature(
            source.secret, timestamp, nonce, response_body)
        return web.Response(
            body=response_body,
            content_type="application/json",
            headers={
                "X-DisRaker-Response-Signature": response_signature,
            },
        )
