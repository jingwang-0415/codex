#!/usr/bin/env python3
"""
Lightweight POST forwarding server for Linux.

Features:
1. Listen on a local HTTP port continuously.
2. Accept POST requests on a configured path.
3. Forward the request body to an upstream HTTP endpoint, or optionally invoke
   a shell command that performs the forwarding.
4. Stream the upstream/command response back to the caller.

Forward mode example:
    python3 stream_command_server.py \
      --port 8080 \
      --path /run \
      --target-url http://127.0.0.1:9000/api/chat

Command mode example:
    python3 stream_command_server.py \
      --port 8080 \
      --path /run \
      --command 'curl -N http://127.0.0.1:9000/api/chat \
        -H "Content-Type: $REQUEST_CONTENT_TYPE" \
        --data-binary @-'
"""

from __future__ import annotations

import argparse
import base64
import http.client
import os
import signal
import socket
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterable
from urllib.parse import urlsplit


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


class StreamingForwardHandler(BaseHTTPRequestHandler):
    server_version = "StreamingForwardHTTP/2.0"
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        self._handle_post()

    def do_GET(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Use POST")

    def log_message(self, fmt: str, *args) -> None:
        print(
            "%s - - [%s] %s"
            % (self.client_address[0], self.log_date_time_string(), fmt % args)
        )

    def _handle_post(self) -> None:
        if self.path.split("?", 1)[0] != self.server.run_path:
            self.send_error(
                HTTPStatus.NOT_FOUND,
                "Only %s is supported" % self.server.run_path,
            )
            return

        # 这里从当前 POST 请求里读取原始 body；后面会把这份 bytes 原样转发出去。
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        request_body = self.rfile.read(content_length) if content_length > 0 else b""

        if self.server.target_url:
            self._forward_http(request_body)
            return

        self._forward_with_command(request_body)

    def _forward_http(self, request_body: bytes) -> None:
        parsed = urlsplit(self.server.target_url)
        if parsed.scheme not in {"http", "https"}:
            self.send_error(HTTPStatus.BAD_GATEWAY, "Unsupported target URL scheme")
            return

        target_path = parsed.path or "/"
        if parsed.query:
            target_path = f"{target_path}?{parsed.query}"

        connection_cls = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        upstream = connection_cls(
            parsed.hostname,
            parsed.port,
            timeout=self.server.upstream_timeout,
        )

        # 转发时尽量复用原请求头，并重新设置与 body 对应的 Content-Length。
        headers = self._build_forward_headers(request_body)
        response_started = False

        try:
            # 关键点在这里：把上游收到的原始 request_body 直接作为下游 POST 的 body 发出去。
            upstream.request("POST", target_path, body=request_body, headers=headers)
            response = upstream.getresponse()

            self.send_response(response.status, response.reason)
            self.send_header(
                "Content-Type",
                response.getheader("Content-Type", "application/octet-stream"),
            )
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Transfer-Encoding", "chunked")

            for key, value in response.getheaders():
                lower_key = key.lower()
                if lower_key in HOP_BY_HOP_HEADERS or lower_key == "content-type":
                    continue
                self.send_header(key, value)

            self.end_headers()
            response_started = True

            # 再把下游返回内容按 chunked 方式持续回写给当前调用方。
            while True:
                chunk = response.read(4096)
                if not chunk:
                    break
                self._write_chunk(chunk)
        except (socket.timeout, OSError, http.client.HTTPException) as exc:
            self.send_error(HTTPStatus.BAD_GATEWAY, "Forward failed: %s" % exc)
        finally:
            try:
                upstream.close()
            finally:
                if response_started:
                    self._finish_chunks()

    def _build_forward_headers(self, request_body: bytes) -> dict[str, str]:
        headers: dict[str, str] = {}

        for key, value in self.headers.items():
            if key.lower() in HOP_BY_HOP_HEADERS:
                continue
            headers[key] = value

        for custom_header in self.server.forward_headers:
            key, value = custom_header.split("=", 1)
            headers[key.strip()] = value.strip()

        headers["Content-Length"] = str(len(request_body))
        if "Content-Type" not in headers and request_body:
            headers["Content-Type"] = "application/octet-stream"

        return headers

    def _forward_with_command(self, request_body: bytes) -> None:
        request_body_text = request_body.decode("utf-8", errors="replace")
        request_body_b64 = base64.b64encode(request_body).decode("ascii")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        env = os.environ.copy()
        env["REQUEST_BODY"] = request_body_text
        env["REQUEST_BODY_BASE64"] = request_body_b64
        env["REQUEST_CONTENT_LENGTH"] = str(len(request_body))
        env["REQUEST_CONTENT_TYPE"] = self.headers.get("Content-Type", "")

        process = subprocess.Popen(
            self.server.command,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            env=env,
        )

        try:
            if process.stdin:
                # 命令模式下，也把收到的原始 body 写入命令 stdin，供 curl 或其他程序继续转发。
                process.stdin.write(request_body)
                process.stdin.close()

            assert process.stdout is not None
            while True:
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    break
                self._write_chunk(chunk)

            return_code = process.wait()
            self._write_chunk(
                f"\n[process exited with code {return_code}]\n".encode("utf-8")
            )
        except (BrokenPipeError, ConnectionResetError):
            self._terminate_process_group(process)
        finally:
            self._finish_chunks()

    def _write_chunk(self, data: bytes) -> None:
        if not data:
            return
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _finish_chunks(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


class ForwardHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        run_path: str,
        target_url: str | None,
        command: str | None,
        forward_headers: Iterable[str],
        upstream_timeout: float,
    ):
        super().__init__(server_address, handler_class)
        self.run_path = run_path
        self.target_url = target_url
        self.command = command
        self.forward_headers = list(forward_headers)
        self.upstream_timeout = upstream_timeout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Listen on an HTTP port and forward POST bodies as a stream."
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host, default: 0.0.0.0")
    parser.add_argument("--port", type=int, required=True, help="Listen port")
    parser.add_argument(
        "--path",
        default="/run",
        help="HTTP path that accepts POST requests, default: /run",
    )
    parser.add_argument(
        "--target-url",
        help="Upstream HTTP/HTTPS URL to receive the forwarded POST body",
    )
    parser.add_argument(
        "--command",
        help=(
            "Optional shell command mode. The request body is available in stdin, "
            "$REQUEST_BODY and $REQUEST_BODY_BASE64."
        ),
    )
    parser.add_argument(
        "--forward-header",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra header to add when forwarding to --target-url; can be repeated",
    )
    parser.add_argument(
        "--upstream-timeout",
        type=float,
        default=3600.0,
        help="Upstream connect/read timeout in seconds, default: 3600",
    )
    args = parser.parse_args()

    if not args.target_url and not args.command:
        parser.error("one of --target-url or --command is required")

    if args.target_url and args.command:
        parser.error("use either --target-url or --command, not both")

    return args


def main() -> None:
    args = parse_args()

    if not args.path.startswith("/"):
        raise SystemExit("--path must start with '/'")

    server = ForwardHTTPServer(
        (args.host, args.port),
        StreamingForwardHandler,
        run_path=args.path,
        target_url=args.target_url,
        command=args.command,
        forward_headers=args.forward_header,
        upstream_timeout=args.upstream_timeout,
    )

    print(f"Listening on http://{args.host}:{args.port}{args.path}")
    if args.target_url:
        print(f"Forward mode: POST body -> {args.target_url}")
    else:
        print(f"Command mode: {args.command}")
        print("Request body is available via stdin and env vars:")
        print("  REQUEST_BODY, REQUEST_BODY_BASE64, REQUEST_CONTENT_LENGTH, REQUEST_CONTENT_TYPE")
    print("Example client:")
    print(f"  curl -N -X POST http://127.0.0.1:{args.port}{args.path} -d 'hello world'")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
