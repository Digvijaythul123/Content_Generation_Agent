from content_agent import ContentAgent
import json
import re
import os

print("Instagram Manager Agent Started\n")

agent = ContentAgent()

result = agent.generate_content()

print(result)

title = re.search(r"Title:\s*(.*)", result)
hook = re.search(r"Hook:\s*(.*)", result)
script = re.search(r"Script:\s*(.*?)Caption:", result, re.DOTALL)
caption = re.search(r"Caption:\s*(.*)", result, re.DOTALL)

data = {
    "title": title.group(1).strip() if title else "",
    "hook": hook.group(1).strip() if hook else "",
    "script": script.group(1).strip() if script else "",
    "caption": caption.group(1).strip() if caption else "",
    "raw_content": result
}

folder_path = "generated_reels"

existing_files = [
    file for file in os.listdir(folder_path)
    if file.endswith(".json")
]

next_number = len(existing_files) + 1

file_name = f"reel_{next_number:03d}.json"

file_path = os.path.join(folder_path, file_name)

with open(file_path, "w") as file:
    json.dump(data, file, indent=4)

print(f"\nContent saved to {file_path}")