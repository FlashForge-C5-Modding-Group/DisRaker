from dataclasses import dataclass
from io import BytesIO
from typing import Any, AsyncIterator, Dict, Optional
from urllib.parse import urljoin

import aiohttp

from .config import MoonrakerConfig


class MoonrakerError(RuntimeError):
    pass


@dataclass(frozen=True)
class CameraImage:
    data: bytes
    filename: str


class MoonrakerClient:
    def __init__(self, config: MoonrakerConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        headers = {}
        if self.config.api_key:
            headers["X-Api-Key"] = self.config.api_key
        connector = aiohttp.TCPConnector(ssl=self.config.verify_ssl)
        self._session = aiohttp.ClientSession(
            timeout=timeout, headers=headers, connector=connector)
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("MoonrakerClient is not open")
        return self._session

    async def _json(self, method: str, path: str, **kwargs) -> Any:
        url = urljoin(self.config.url + "/", path.lstrip("/"))
        try:
            async with self.session.request(method, url, **kwargs) as response:
                payload = await response.json(content_type=None)
                if response.status >= 400:
                    raise MoonrakerError(
                        "Moonraker returned HTTP {}: {}".format(
                            response.status, payload))
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise MoonrakerError("Unable to contact Moonraker: {}".format(
                exc)) from exc
        if not isinstance(payload, dict):
            raise MoonrakerError("Moonraker returned malformed JSON")
        if "error" in payload:
            raise MoonrakerError("Moonraker error: {}".format(payload["error"]))
        result = payload.get("result", payload)
        return result

    async def status(self) -> Dict[str, Any]:
        objects: Dict[str, Any] = {
            "print_stats": None,
            "virtual_sdcard": None,
            "display_status": None,
            "webhooks": None,
            "idle_timeout": None,
            "gcode_move": None,
            "toolhead": None,
            "motion_report": None,
            "fan": None,
            "system_stats": None,
        }
        for name in self.config.temperature_objects:
            objects[name] = None
        result = await self._json("POST", "/server/jsonrpc", json={
            "jsonrpc": "2.0",
            "method": "printer.objects.query",
            "params": {"objects": objects},
            "id": 1,
        })
        status = result.get("status", {})
        if not isinstance(status, dict):
            raise MoonrakerError("Moonraker status result is malformed")
        return status

    async def printer_info(self) -> Dict[str, Any]:
        result = await self._json("GET", "/printer/info")
        if not isinstance(result, dict):
            raise MoonrakerError("Moonraker printer info is malformed")
        return result

    async def pause_print(self):
        await self._json("POST", "/printer/print/pause")

    async def resume_print(self):
        await self._json("POST", "/printer/print/resume")

    async def cancel_print(self):
        await self._json("POST", "/printer/print/cancel")

    async def status_updates(self) -> AsyncIterator[Dict[str, Any]]:
        url = urljoin(self.config.url + "/", "websocket")
        if url.startswith("https://"):
            url = "wss://" + url[len("https://"):]
        elif url.startswith("http://"):
            url = "ws://" + url[len("http://"):]
        try:
            async with self.session.ws_connect(url, heartbeat=30.0) as socket:
                await socket.send_json({
                    "jsonrpc": "2.0",
                    "method": "printer.objects.subscribe",
                    "params": {"objects": {"print_stats": None}},
                    "id": 2,
                })
                async for message in socket:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        payload = message.json()
                        if payload.get("id") == 2:
                            status = payload.get("result", {}).get("status", {})
                        elif payload.get("method") == "notify_status_update":
                            params = payload.get("params", [])
                            status = params[0] if params else {}
                        else:
                            continue
                        if isinstance(status, dict):
                            yield status
                    elif message.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR):
                        break
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise MoonrakerError(
                "Moonraker WebSocket disconnected: {}".format(exc)) from exc

    async def _snapshot_url(self) -> str:
        if self.config.snapshot_url:
            return urljoin(self.config.url + "/", self.config.snapshot_url)
        result = await self._json("GET", "/server/webcams/list")
        webcams = result.get("webcams", [])
        if not webcams:
            raise MoonrakerError("Moonraker has no configured webcams")
        selected = None
        if self.config.camera_name:
            selected = next((camera for camera in webcams
                             if camera.get("name") == self.config.camera_name),
                            None)
        selected = selected or webcams[0]
        snapshot_url = selected.get("snapshot_url")
        if not snapshot_url:
            raise MoonrakerError("Selected webcam has no snapshot URL")
        return urljoin(self.config.url + "/", snapshot_url)

    async def camera_image(self) -> CameraImage:
        url = await self._snapshot_url()
        try:
            async with self.session.get(url) as response:
                if response.status >= 400:
                    raise MoonrakerError(
                        "Camera returned HTTP {}".format(response.status))
                data = await response.read()
                content_type = response.headers.get("Content-Type", "")
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise MoonrakerError("Unable to fetch camera image: {}".format(
                exc)) from exc
        if not data:
            raise MoonrakerError("Camera returned an empty image")
        extension = ".png" if "png" in content_type else ".jpg"
        return CameraImage(data=data, filename="printer" + extension)

    async def camera_file(self):
        image = await self.camera_image()
        return BytesIO(image.data), image.filename
