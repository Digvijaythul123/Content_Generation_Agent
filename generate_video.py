import json
import os
import sys

if len(sys.argv) != 2:
    print("Usage: python3 generate_video.py <reel_id>")
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

title = reel.get("title", "")
hook = reel.get("hook", "")
script = reel.get("script", "")
caption = reel.get("caption", "")

output_folder = "generated_videos"
os.makedirs(output_folder, exist_ok=True)

output_file = os.path.join(
    output_folder,
    f"{reel_id}_video_plan.txt"
)

with open(output_file, "w") as file:

    file.write("VIDEO PLAN\n")
    file.write("=" * 50 + "\n\n")

    file.write(f"TITLE:\n{title}\n\n")
    file.write(f"HOOK:\n{hook}\n\n")

    file.write("SCRIPT:\n")
    file