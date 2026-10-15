import json
import os

folder = "generated_reels"

for file_name in sorted(os.listdir(folder)):
    if file_name.endswith(".json"):
        file_path = os.path.join(folder, file_name)

        with open(file_path, "r") as file:
            reel = json.load(file)

        reel_id = reel.get("id", "NO_ID")
        status = reel.get("status", "UNKNOWN")
        title = reel.get("title", "NO_TITLE")

        print(f"{reel_id} | {status} | {title}")