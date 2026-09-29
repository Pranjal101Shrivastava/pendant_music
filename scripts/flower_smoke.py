"""No-key integration check: real SuperLink -> mock Responses HTTP server.

Run with the optional dependencies installed: python scripts/flower_smoke.py
Uses temporary runtime config and loopback ports. Does not call a real model.
"""
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agents.offline import compose, play
from flwr.cli.build import build_fab_from_disk
from flwr.common.serde import user_config_to_proto
from flwr.proto.control_pb2 import StartRunRequest, ListRunsRequest
from flwr.proto.fab_pb2 import Fab
from flwr.supercore.control.control_http_client import ControlHttpClient
import hashlib


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    bp = compose("upbeat funk, 110 BPM", 8, seed=0)
    parts = {}
    for role in ("drums", "bass", "chords", "melody"):
        parts[role] = play(role, bp, parts, 0, 0)
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            schema = payload.get("text", {}).get("format", {}).get("name", "title")
            if schema == "blueprint":
                value = bp
            elif schema == "arrangement":
                value = {"order": list(parts), "reason": "rhythm first"}
            elif schema == "critic_report":
                value = {"verdict": "accept", "summary": "mock transport test", "issues": [],
                         "scores": {k: 4 for k in ("groove", "harmonic_fit", "variation", "balance")}}
            elif schema in {"part", "part_with_feedback"}:
                messages = payload["input"]
                role = re.search(r"Your instrument: (\w+)", messages[0]["content"])[1]
                value = {"notes": parts[role]}
                if schema == "part_with_feedback":
                    value["feedback_to_composer"] = ""
            else:
                value = "Pendant smoke test"
            output = [{"type": "message", "id": "msg_smoke", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": json.dumps(value), "annotations": []}]}]
            if payload.get("tools") and not any(i.get("type") == "function_call_output" for i in payload["input"]):
                output = [{"type": "function_call", "id": "fc_smoke", "call_id": "call_smoke",
                           "name": "check_my_part", "arguments": json.dumps({"notes": value["notes"]}),
                           "status": "completed"}]
            body = json.dumps({"id": "resp_smoke", "object": "response", "created_at": 0,
                               "model": payload.get("model", "test"), "status": "completed", "output": output,
                               "parallel_tool_calls": False, "tool_choice": "auto", "tools": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="pendant-flower-") as temp:
            temp = Path(temp)
            port, fleet_port = free_port(), free_port()
            env = dict(os.environ)
            env.update(FLWR_HOME=str(temp / "flwr"), PATH=str(Path(sys.executable).parent) + os.pathsep + env["PATH"],
                       FLWR_MODEL_API_ENDPOINT=f"http://127.0.0.1:{server.server_port}/v1/responses",
                       FLWR_MODEL_API_KEY="test-placeholder", PENDANT_MODEL_MELODY="smoke-melody")
            (temp / "flwr").mkdir()
            (temp / "flwr/config.toml").write_text(
                f'[superlink]\ndefault = "smoke"\n[superlink.smoke]\naddress = "127.0.0.1:{port}"\ninsecure = true\n')
            with (temp / "superlink.log").open("w") as log:
                process = subprocess.Popen(["flower-superlink", "--insecure", "--host", "127.0.0.1", "--port", str(port),
                                            "--fleet-api-address", f"127.0.0.1:{fleet_port}",
                                            "--disable-runtime-dependency-installation"], env=env, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    deadline = time.monotonic() + 25
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError("SuperLink failed to start")
                        try:
                            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                                break
                        except OSError:
                            time.sleep(0.2)
                    fab = build_fab_from_disk(ROOT)
                    client = ControlHttpClient(f"http://127.0.0.1:{port}")
                    for provider in ("offline", "openai"):
                        out = temp / provider
                        started = client.StartRun(StartRunRequest(
                            user_prompt="upbeat funk, 110 BPM",
                            fab=Fab(hash_str=hashlib.sha256(fab).hexdigest(), content=fab),
                            override_config=user_config_to_proto({"provider": provider, "mode": "autonomous",
                                                                  "bars": 8, "output-dir": str(out)})))
                        deadline = time.monotonic() + 120
                        while time.monotonic() < deadline:
                            status = client.ListRuns(ListRunsRequest(run_id=started.run_id)).run_dict[started.run_id].status
                            if status.status == "finished":
                                if status.sub_status != "completed":
                                    raise RuntimeError(f"Flower {provider} run failed: {status}")
                                break
                            time.sleep(0.25)
                        else:
                            raise TimeoutError("Flower run exceeded 120 seconds")
                        songs = list(out.rglob("song.mid"))
                        assert len(songs) == 1, "Flower run did not produce a MIDI file"
                        assert songs[0].read_bytes().startswith(b"MThd")
                        report = json.loads(songs[0].with_name("report.json").read_text())
                        assert report["api_calls"] <= 60
                        print(f"PASS: {provider} autonomous run, {report['api_calls']} calls", flush=True)
                    music = [r for r in requests if r.get("text", {}).get("format", {}).get("name") != "conversation_title"
                             and r.get("text", {}).get("format", {}).get("name") in {"blueprint", "arrangement", "part_with_feedback", "critic_report"}]
                    assert len(music) == 11, f"Expected 11 requests, got {len(music)}"
                    assert all(r["text"]["format"]["strict"] for r in music)
                    assert sum(any(i.get("type") == "function_call_output" for i in r["input"]) for r in music) == 4
                    assert any(r["model"] == "smoke-melody" for r in music)
                    print("PASS: real Flower offline and mock-backed autonomous runs; 11 music requests, four self-check round-trips.")
                except BaseException:
                    print((temp / "superlink.log").read_text()[-15000:], file=sys.stderr)
                    raise
                finally:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
