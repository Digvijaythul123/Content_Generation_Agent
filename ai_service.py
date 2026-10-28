import time

import requests

from app_settings import (
    DEFAULT_MODEL_ENDPOINT,
    DEFAULT_MODEL_NAME,
    get_setting,
)


# TEXT_PROVIDER=gemini writes with Google Gemini (GEMINI_API_KEY, free tier
# from Google AI Studio) and falls back to Ollama when Gemini's daily limit
# is reached or it cannot be reached. TEXT_PROVIDER=ollama (the default)
# uses only Ollama (MODEL_ENDPOINT, MODEL_NAME).
DEFAULT_GEMINI_TEXT_MODEL = "gemini-3.5-flash"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

GEMINI_RETRY_SECONDS = 4

# The model behind the latest successful call, saved on new drafts so
# Gemini and Ollama drafts can be compared.
last_model_used = None


class AIServiceError(RuntimeError):
    """Raised when the configured model service fails or returns bad data."""


class _GeminiUnavailable(AIServiceError):
    """Gemini is over its limit or unreachable; Ollama may take over."""


class AIService:

    def generate_reel(self, prompt):
        global last_model_used
        if (get_setting("TEXT_PROVIDER", "ollama") or "ollama").lower() == "gemini":
            model = get_setting("GEMINI_TEXT_MODEL", DEFAULT_GEMINI_TEXT_MODEL)
            try:
                try:
                    text = self._gemini(prompt, model)
                except _GeminiUnavailable:
                    # "High demand" spikes usually pass within seconds.
                    time.sleep(GEMINI_RETRY_SECONDS)
                    text = self._gemini(prompt, model)
                last_model_used = f"gemini:{model}"
                return text
            except _GeminiUnavailable:
                if (get_setting("GEMINI_FALLBACK", "ollama") or "").lower() != "ollama":
                    raise
        text = self._ollama(prompt)
        last_model_used = f"ollama:{get_setting('MODEL_NAME', DEFAULT_MODEL_NAME)}"
        return text

    def _gemini(self, prompt, model):
        key = get_setting("GEMINI_API_KEY")
        if not key:
            raise AIServiceError("TEXT_PROVIDER is gemini but GEMINI_API_KEY is not in .env.")
        try:
            response = requests.post(
                _GEMINI_URL.format(model=model),
                # The key goes in a header so it never appears in an error URL.
                headers={"x-goog-api-key": key},
                json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
                timeout=180,
            )
        except requests.RequestException as error:
            raise _GeminiUnavailable(
                f"Could not reach Gemini ({type(error).__name__})."
            ) from error
        try:
            result = response.json()
        except ValueError:
            result = {}
        if response.status_code == 429 or response.status_code >= 500:
            raise _GeminiUnavailable(
                f"Gemini is unavailable (HTTP {response.status_code}): "
                f"{(result.get('error') or {}).get('message', 'no details')}"
            )
        if response.status_code >= 400:
            raise AIServiceError(
                f"Gemini returned HTTP {response.status_code}: "
                f"{(result.get('error') or {}).get('message', 'no details')}"
            )
        candidates = result.get("candidates") or []
        parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
        # Skip the model's thinking; keep only the answer.
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        if not text.strip():
            reason = candidates[0].get("finishReason") if candidates else (
                (result.get("promptFeedback") or {}).get("blockReason"))
            raise AIServiceError(f"Gemini returned no text ({reason or 'empty reply'}).")
        return text

    def _ollama(self, prompt):
        try:
            response = requests.post(
                get_setting("MODEL_ENDPOINT", DEFAULT_MODEL_ENDPOINT),
                json={
                    "model": get_setting("MODEL_NAME", DEFAULT_MODEL_NAME),
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=180,
            )
            response.raise_for_status()
        except requests.Timeout as error:
            raise AIServiceError(
                "The model request timed out after 180 seconds."
            ) from error
        except requests.HTTPError as error:
            raise AIServiceError(
                f"The model service returned an HTTP error: {error}"
            ) from error
        except requests.RequestException as error:
            raise AIServiceError(
                f"Could not connect to the model service: {error}"
            ) from error

        try:
            result = response.json()
        except ValueError as error:
            raise AIServiceError(
                "The model service returned invalid JSON."
            ) from error

        if not isinstance(result, dict):
            raise AIServiceError(
                "The model service response must be a JSON object."
            )
        generated_text = result.get("response")
        if not isinstance(generated_text, str) or not generated_text.strip():
            raise AIServiceError(
                "The model service response is missing non-empty text in "
                "the 'response' field."
            )
        return generated_text
