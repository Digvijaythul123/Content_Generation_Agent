import json
import os

folder = "generated_reels"

for file_name in sorted(os.listdir(folder)):
    if file_name.endswith(".json"):

        file_path = os.path.join(folder, file_name)

        with open(file_path, "r") as file:
            reel = json.load(file)

        if reel.get("status") == "Approved":
            print(
                f"{reel.get('id', 'NO_ID')} | "
                f"{reel.get('title', 'NO_TITLE')}"
            )