import requests


class AIService:

    def generate_reel(self, prompt):

        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3.2",
                "prompt": prompt,
                "stream": False
            }
        )

        result = response.json()

        return result["response"]