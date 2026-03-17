from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .models import GenerationRequest
from .service import HyperLocalAdStudio

WEB_ROOT = Path(__file__).resolve().parent / "web"

_MAX_BODY_BYTES = 65_536  # 64 KB
_MAX_TARGET_VARIANTS = 200
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


def _sample_requests() -> list[dict[str, object]]:
    return [
        {
            "label": "European Wax Center",
            "corporate_prompt": "Drive membership enrollments for our Smooth Skin Guarantee — unlimited wax services for a flat monthly rate",
            "zip_codes": ["33139", "10001", "90012", "77002"],
            "brand_guardrails": "Tone: confident, empowering, and polished. Avoid clinical language. Stay aspirational and conversion-focused.",
            "target_variants": 4,
        },
        {
            "label": "The UPS Store",
            "corporate_prompt": "Drive in-store traffic for same-day shipping, printing, and mailbox services targeting small businesses and remote workers",
            "zip_codes": ["10036", "94103", "60611", "02108"],
            "brand_guardrails": "Lead with convenience and reliability. Keep copy clear, direct, and action-oriented. Avoid jargon.",
            "target_variants": 4,
        },
        {
            "label": "Sylvan Learning",
            "corporate_prompt": "Drive enrollment for personalized K-12 tutoring programs ahead of the new school year",
            "zip_codes": ["11201", "80202", "78641", "94087"],
            "brand_guardrails": "Speak to parents. Warm, encouraging, and results-focused tone. Emphasize trust, personalization, and measurable outcomes.",
            "target_variants": 4,
        },
        {
            "label": "Single Location",
            "corporate_prompt": "Drive membership enrollments for our Smooth Skin Guarantee — unlimited wax services for a flat monthly rate",
            "zip_codes": ["10044"],
            "brand_guardrails": "Tone: confident, empowering, and polished. Stay aspirational.",
            "target_variants": 1,
        },
    ]


class PortfolioHandler(BaseHTTPRequestHandler):
    server_version = "HyperLocalAdStudio/0.1"

    @property
    def studio(self) -> HyperLocalAdStudio:
        return self.server.studio  # type: ignore[attr-defined]

    @property
    def _loop(self) -> asyncio.AbstractEventLoop:
        return self.server._event_loop  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._write_json(
                HTTPStatus.OK,
                {
                    "runtime": self.studio.runtime_status(),
                    "samples": _sample_requests(),
                },
            )
            return
        if parsed.path == "/api/trace":
            query = parse_qs(parsed.query)
            request_id = query.get("request_id", [""])[0].strip()
            zip_code = query.get("zip_code", [""])[0].strip()
            if not request_id or not zip_code:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "request_id and zip_code are required."})
                return
            try:
                trace = self.studio.load_trace_events(request_id=request_id, zip_code=zip_code)
            except FileNotFoundError:
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "Trace not found."})
                return
            self._write_json(HTTPStatus.OK, {"request_id": request_id, "zip_code": zip_code, "events": trace})
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/generate":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("application/json"):
            self._write_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"error": "Content-Type must be application/json."},
            )
            return
        try:
            payload = self._read_json_body()
            zip_codes_raw = [str(z).strip() for z in payload["zip_codes"]]
            for z in zip_codes_raw:
                if not _ZIP_RE.match(z):
                    raise ValueError(f"Invalid zip code: {z!r}. Expected 5-digit US format (e.g. 10001).")
            generation_request = GenerationRequest(
                corporate_prompt=str(payload["corporate_prompt"]).strip(),
                zip_codes=zip_codes_raw,
                brand_guardrails=str(payload.get("brand_guardrails", "")).strip(),
                target_variants=min(_MAX_TARGET_VARIANTS, max(1, int(payload.get("target_variants", 50)))),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        future = asyncio.run_coroutine_threadsafe(
            self.studio.generate_batch(generation_request), self._loop
        )
        try:
            result = future.result(timeout=300)
        except Exception as exc:  # pragma: no cover
            self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Generation failed."})
            return
        self._write_json(HTTPStatus.OK, result.to_dict())

    def _serve_static(self, raw_path: str) -> None:
        normalized = raw_path.rstrip("/") or "/"
        if normalized == "/":
            candidate = WEB_ROOT / "index.html"
        else:
            safe_path = unquote(normalized).lstrip("/")
            candidate = (WEB_ROOT / safe_path).resolve()
            if WEB_ROOT.resolve() not in candidate.parents and candidate != WEB_ROOT.resolve():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
        if not candidate.exists() or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        content = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(content)

    def _read_json_body(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > _MAX_BODY_BYTES:
            raise ValueError(f"Request body exceeds {_MAX_BODY_BYTES} byte limit.")
        raw_body = self.rfile.read(content_length).decode("utf-8")
        return json.loads(raw_body)

    def _write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str, port: int) -> None:
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    server = ThreadingHTTPServer((host, port), PortfolioHandler)
    server.studio = HyperLocalAdStudio()  # type: ignore[attr-defined]
    server._event_loop = loop  # type: ignore[attr-defined]
    print(f"HyperLocal Agentic Ad Studio running at http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the browser-based HyperLocal Ad Studio demo.")
    parser.add_argument("--host", default=os.getenv("HYPERLOCAL_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("HYPERLOCAL_WEB_PORT", "8000")))
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
