import json
import os
import re
import sys

if len(sys.argv) != 2:
    print("Usage: python3 scene_generator.py <reel_id>")
    sys.exit(1)

reel_id = sys.argv[1]

file_path = os.path.join(
    "generated_reels",
    f"{reel_id}.json"
)

if not os.path.exists(file_path):
    print(f"Reel not found: {reel_id}")
    sys.exit(1)

with open(file_path, "r") as file:
    reel = json.load(file)

hook = reel.get("hook", "")
script = reel.get("script", "")

# Remove visual instructions
script = re.sub(
    r"\(Visual:.*?\)",
    "",
    script,
    flags=re.IGNORECASE | re.DOTALL
)

# Remove remaining brackets
script = re.sub(r"\(.*?\)", "", script)

# Remove quote artifacts
script = script.replace('"', "")

# Normalize whitespace
script = script.replace("\n", " ")
script = re.sub(r"\s+", " ", script).strip()

scenes = []

if hook:
    scenes.append(hook.strip())

sentences = re.split(r"(?<=[.!?])\s+", script)

for sentence in sentences:

    sentence = sentence.strip()

    if not sentence:
        continue

    if len(sentence) < 30:
        continue

    scenes.append(sentence)

output_folder = "generated_videos"
os.makedirs(output_folder, exist_ok=True)

output_file = os.path.join(
    output_folder,
    f"{reel_id}_scenes.txt"
)

with open(output_file, "w") as file:

    file.write("SCENES\n")
    file.write("=" * 50)
    file.write("\n\n")

    for index, scene in enumerate(scenes, start=1):

        file.write(f"SCENE {index}\n")
        file.write(scene)
        file.write("\n\n")

print(f"Scenes saved to {output_file}")