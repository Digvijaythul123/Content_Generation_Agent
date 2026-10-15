import json
import os

folder = "generated_reels"

for file_name in sorted(os.listdir(folder)):
    if not file_name.endswith(".json"):
        continue

    file_path = os.path.join(folder, file_name)

    with open(file_path, "r") as file:
        reel = json.load(file)

    print("\n" + "=" * 80)
    print(f"ID: {reel.get('id', 'NO_ID')}")
    print(f"Status: {reel.get('status', 'UNKNOWN')}")
    print(f"Title: {reel.get('title', 'NO_TITLE')}")
    print(f"Hook: {reel.get('hook', '')}")

    choice = input("\n[A]pprove / [R]eject / [S]kip ? ").strip().lower()

    if choice == "a":
        reel["status"] = "Approved"

    elif choice == "r":
        reel["status"] = "Rejected"

    elif choice == "s":
        continue

    with open(file_path, "w") as file:
        json.dump(reel, file, indent=4)

    print("Updated.")