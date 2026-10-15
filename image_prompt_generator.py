from ai_service import AIService
import os
import sys

if len(sys.argv) != 2:
    print("Usage: python3 image_prompt_generator.py <reel_id>")
    sys.exit(1)

reel_id = sys.argv[1]

scene_file = os.path.join(
    "generated_videos",
    f"{reel_id}_scenes.txt"
)

if not os.path.exists(scene_file):
    print("Scenes file not found")
    sys.exit(1)

with open(scene_file, "r") as file:
    scene_content = file.read()

ai_service = AIService()

prompt = f"""
You are an expert visual storyteller.

Convert each scene into a professional AI image prompt.

Requirements:
- Photorealistic
- Cinematic
- Vertical Instagram Reel format
- Modern Indian professional setting
- Rich visual detail
- No text inside image
- One image prompt per scene

Scenes:

{scene_content}
"""

result = ai_service.generate_reel(prompt)

output_file = os.path.join(
    "generated_videos",
    f"{reel_id}_image_prompts.txt"
)

with open(output_file, "w") as file:
    file.write(result)

print(
    f"Image prompts saved to {output_file}"
)