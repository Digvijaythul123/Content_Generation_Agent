from ai_service import AIService


class ContentAgent:

    def __init__(self):
        self.ai_service = AIService()

    def generate_content(self):
        return self.ai_service.generate_reel_ideas()
