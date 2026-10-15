import requests


class AIService:

    def generate_reel(self, prompt):

        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma4:31b-cloud",
                "prompt": prompt,
                "stream": False
            }
        )

        result = response.json()

        return result["response"]