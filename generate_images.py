import os
import re
import sys

if len(sys.argv) != 2:
    print("Usage: python3 generate_images.py <reel_id>")
    sys.exit(1)

reel_id = sys.argv[1]

prompt_file = os.path.join(
    "generated_videos",
    f"{reel_id}_image_prompts.txt"
)

if not os.path.exists(prompt_file):
    print(f"Prompt file not found: {prompt_file}")
    sys.exit(1)

with open(prompt_file, "r") as file:
    content = file.read()

output_folder = os.path.join(
    "generated_images",
    reel_id
)

os.makedirs(output_folder, exist_ok=True)

matches = re.findall(
    r"\*\*SCENE\s+(\d+)\*\*.*?\*\*Prompt:\*\*\s*(.*?)(?=\*\*SCENE|\Z)",
    content,
    re.DOTALL
)

for scene_number, prompt in matches:

    prompt = prompt.strip()

    file_path = os.path.join(
        output_folder,
        f"scene_{scene_number}.txt"
    )

    with open(file_path, "w") as file:
        file.write(prompt)

print(
    f"{len(matches)} scene prompt files created in {output_folder}"
)