from ai_service import AIService


class ContentAgent:

    def __init__(self):
        self.ai_service = AIService()

    def generate_content(self):

        prompt = """
You are a viral Instagram content strategist.

Create ONE reel idea for a page called Rational Thoughts.

Audience:
- Indian professionals
- Age 25-40

Rules:
- No generic advice
- Challenge common beliefs
- Use first-principles thinking
- Be thought provoking

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