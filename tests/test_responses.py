"""Exercise Responses serialization with the real SDK and an in-process HTTP server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from openai import OpenAI

from core.config import Settings
from core.json_schemas import PART
from core.llm import BudgetExceeded, CallBudget, LLMError, LLMOutputError, OpenAIResponsesProvider

ASK = dict(agent="melody", system="Write notes", messages=[{"role": "user", "content": "hi"}],
           schema_name="part", schema=PART)


def response(output=None, status="completed", text='{"notes": []}'):
    return {"id": "resp_test", "object": "response", "created_at": 0, "model": "test",
            "status": status, "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
            "output": output if output is not None else [{"type": "message", "id": "msg_1",
                "role": "assistant", "status": "completed", "content": [
                    {"type": "output_text", "text": text, "annotations": []}]}]}


@pytest.fixture
def server():
    requests, replies = [], []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps(replies.pop(0)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    client = OpenAI(base_url=f"http://127.0.0.1:{http.server_port}/v1", api_key="test-placeholder", max_retries=0)
    yield client, requests, replies
    client.close()
    http.shutdown()
    http.server_close()
    thread.join()


def test_responses_tool_roundtrip_preserves_reasoning_and_model(server):
    client, requests, replies = server
    replies.extend([response(output=[
        {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"},
        {"type": "function_call", "id": "fc_1", "call_id": "call_1",
         "name": "check_my_part", "arguments": '{"notes": []}', "status": "completed"},
    ]), response()])
    settings = Settings(models={"melody": "custom-model"}, reasoning_effort="low")
    provider = OpenAIResponsesProvider(settings, CallBudget(2), client)
    seen = []
    assert provider.generate(**ASK, tools={"check_my_part": ("validate", PART,
                              lambda args: seen.append(args) or "OK")}) == {"notes": []}
    assert seen == [{"notes": []}]
    assert len(requests) == provider.budget.used == 2
    assert all(r["model"] == "custom-model" for r in requests)
    assert requests[0]["text"]["format"]["strict"] is True
    assert requests[0]["tools"][0]["strict"] is True
    assert requests[0]["store"] is False
    assert requests[1]["input"][-1] == {"type": "function_call_output", "call_id": "call_1", "output": "OK"}
    assert requests[1]["input"][1]["encrypted_content"] == "opaque"
    assert "previous_response_id" not in requests[1]


@pytest.mark.parametrize("reply, error", [
    (response(status="incomplete"), LLMOutputError),
    (response(status="failed"), LLMError),
    (response(text="not JSON"), LLMOutputError),
    (response(text="[]"), LLMOutputError),
    (response(output=[{"type": "message", "id": "m", "role": "assistant", "content": [
        {"type": "refusal", "refusal": "No"}]}]), LLMError),
])
def test_responses_errors(server, reply, error):
    client, _, replies = server
    replies.append(reply)
    with pytest.raises(error):
        OpenAIResponsesProvider(Settings(), CallBudget(1), client).generate(**ASK)


def test_responses_budget_stops_before_second_request(server):
    client, requests, replies = server
    replies.append(response(output=[{"type": "function_call", "call_id": "c", "name": "check_my_part",
                                     "arguments": '{"notes": []}'}]))
    p = OpenAIResponsesProvider(Settings(), CallBudget(1), client)
    with pytest.raises(BudgetExceeded):
        p.generate(**ASK, tools={"check_my_part": ("check", PART, lambda a: "OK")})
    assert len(requests) == 1


def test_responses_last_round_disables_tools(server):
    client, requests, replies = server
    replies.append(response())
    p = OpenAIResponsesProvider(Settings(), CallBudget(1), client)
    p.generate(**ASK, tools={"check_my_part": ("check", PART, lambda a: "OK")}, max_tool_rounds=0)
    assert requests[0]["tool_choice"] == "none"
