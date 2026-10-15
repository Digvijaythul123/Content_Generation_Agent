import json
import os
import sys

if len(sys.argv) != 2:
    print("Usage: python3 reject_reel.py <reel_id>")
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

reel["status"] = "Rejected"

with open(file_path, "w") as file:
    json.dump(reel, file, indent=4)

print(f"{reel_id} rejected successfully")
