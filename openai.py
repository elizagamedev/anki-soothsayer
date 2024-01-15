import json
import random
import sys
import time
from http.client import HTTPSConnection
from typing import Any

# https://platform.openai.com/docs/guides/error-codes/api-errors
ACCEPTABLE_ERRORS = frozenset([429, 500, 503])
QUOTA_ERROR = (
    "You exceeded your current quota, please check your plan and billing details"
)


class OpenAIError(Exception):
    pass


class OpenAIConnection:
    api_key: str
    timeout: int
    max_retries: int

    def __init__(
        self,
        api_key: str,
        timeout: int,
        max_retries: int,
    ):
        self.connection = HTTPSConnection("api.openai.com", timeout=timeout)
        self.max_retries = max_retries
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    def close(self) -> None:
        self.connection.close()

    def _simple_request(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        # https://cookbook.openai.com/examples/how_to_handle_rate_limits#example-3-manual-backoff-implementation
        num_retries = 0
        delay = 1.0
        while True:
            try:
                self.connection.request(
                    "POST",
                    endpoint,
                    json.dumps(payload, separators=(",", ":")),
                    self.headers,
                )
                response = self.connection.getresponse()
                result: dict[str, Any] = json.load(response)

                if response.status == 200:
                    break

                message = f"HTTP Error {response.status}: {response.reason}"

                if (
                    response.status in ACCEPTABLE_ERRORS
                    and response.reason != QUOTA_ERROR
                ):
                    print(f"{message}, retries={num_retries}", file=sys.stderr)
                    num_retries += 1
                    if num_retries >= self.max_retries:
                        raise OpenAIError(message)
                    delay *= 2 * (1 + random.random())
                    time.sleep(delay)
                else:
                    raise OpenAIError(message)
            except Exception as e:
                # TODO: Should we treat all other errors as fatal?
                raise OpenAIError(str(e))

        # Check for API-level errors.
        error = result.get("error")
        if error:
            raise OpenAIError(str(error))

        return result

    def _simple_chat_request(
        self, query: str, request_options: dict[str, Any]
    ) -> dict[str, Any]:
        return self._simple_request(
            "/v1/chat/completions",
            request_options | {"messages": [{"role": "user", "content": query}]},
        )

    def ask(self, query: str, request_options: dict[str, Any]) -> str:
        result = self._simple_chat_request(query, request_options)
        content: str = result["choices"][0]["message"]["content"]
        return content
