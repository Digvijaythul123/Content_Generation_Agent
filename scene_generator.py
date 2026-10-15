import json
import os
import sys
import re

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

output_folder = "generated_videos"
os.makedirs(output_folder, exist_ok=True)

sentences = []

if hook:
    sentences.append(hook)

script = re.sub(r"\(.*?\)", "", script)

for sentence in re.split(r"[.!?]+", script):
    sentence = sentence.strip()

    if len(sentence) > 20:
        sentences.append(sentence)

output_file = os.path.join(
    output_folder,
    f"{reel_id}_scenes.txt"
)

with open(output_file, "w") as file:

    file.write("SCENES\n")
    file.write("=" * 50 + "\n\n")

    for index, sentence in enumerate(sentences, start=1):

        file.write(f"SCENE {index}\n")
        file.write(sentence)
        file.write("\n\n")

print(f"Scenes saved to {output_file}")