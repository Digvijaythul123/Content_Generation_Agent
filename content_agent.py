from ai_service import AIService
import json
import os


class ContentAgent:

    def __init__(self):
        self.ai_service = AIService()

    def get_previous_titles(self):

        folder = "generated_reels"

        if not os.path.exists(folder):
            return []

        titles = []

        for file_name in os.listdir(folder):

            if not file_name.endswith(".json"):
                continue

            file_path = os.path.join(folder, file_name)

            try:
                with open(file_path, "r") as file:
                    reel = json.load(file)

                title = reel.get("title")

                if title:
                    titles.append(title)

            except Exception:
                pass

        return titles

    def generate_content(self):

        previous_titles = self.get_previous_titles()

        previous_titles_text = "\n".join(
            [f"- {title}" for title in previous_titles]
        )

        prompt = f"""
You are a viral Instagram content strategist.

Create ONE reel idea for a page called Rational Thoughts.

Audience:
- Indian professionals
- Age 25-40

Previously generated titles:

{previous_titles_text}

Rules:
- Do NOT repeat any previous title
- Do NOT generate variations of previous titles
- Do NOT generate similar ideas
- No generic advice
- No productivity tips
- No motivational clichés
- Challenge common beliefs
- Use first-principles thinking
- Be thought provoking
- Be contrarian
- Create curiosity
- Make people stop scrolling

Generate ideas around:
- Career
- Money
- Status
- Success
- Society
- Human behavior
- Decision making
- Psychology

Output exactly in this format:

Title:
Hook:
Script:
Caption:

Do not include:
- Reel Idea
- Notes
- Explanations
- Analysis
- Additional commentary

Only provide the four sections above.
"""

        return self.ai_service.generate_reel(prompt)