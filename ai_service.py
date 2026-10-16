import requests


class AIServiceError(RuntimeError):
    """Raised when the configured model service fails or returns bad data."""


class AIService:

    def generate_reel(self, prompt):
        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "gemma4:31b-cloud",
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