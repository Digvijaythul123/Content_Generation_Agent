import os
import sys

if len(sys.argv) != 2:
    print("Usage: python3 image_prompt_generator.py <reel_id>")
    sys.exit(1)

reel_id = sys.argv[1]

scenes_file = os.path.join(
    "generated_videos",
    f"{reel_id}_scenes.txt"
)

if not os.path.exists(scenes_file):
    print(f"Scenes file not found: {scenes_file}")
    sys.exit(1)

with open(scenes_file, "r") as file:
    content = file.read()

scenes = []

for line in content.splitlines():

    line = line.strip()

    if (
        not line
        or line.startswith("SCENES")
        or line.startswith("=")
        or line.startswith("SCENE ")
    ):
        continue

    scenes.append(line)

output_file = os.path.join(
    "generated_videos",
    f"{reel_id}_image_prompts.txt"
)

with open(output_file, "w") as file:

    file.write("IMAGE PROMPTS\n")
    file.write("=" * 50 + "\n\n")

    for index, scene in enumerate(scenes, start=1):

        prompt = (
            f"Photorealistic cinematic scene, {scene}, "
            f"modern Indian professional environment, "
            f"high detail, realistic lighting, "
            f"Instagram reel style, vertical composition"
        )

        file.write(f"PROMPT {index}\n")
        file.write(prompt)
        file.write("\n\n")

print(f"Image prompts saved to {output_file}")