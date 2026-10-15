import json
import os
import re
import sys

if len(sys.argv) != 2:
    print("Usage: python3 video_prompt_generator.py <reel_id>")
    sys.exit(1)

reel_id = sys.argv[1]

reel_file = os.path.join(
    "generated_reels",
    f"{reel_id}.json"
)

image_prompt_file = os.path.join(
    "generated_videos",
    f"{reel_id}_image_prompts.txt"
)

if not os.path.exists(reel_file):
    print(f"Reel not found: {reel_file}")
    sys.exit(1)

if not os.path.exists(image_prompt_file):
    print(f"Image prompt file not found: {image_prompt_file}")
    sys.exit(1)

with open(reel_file, "r") as file:
    reel = json.load(file)

with open(image_prompt_file, "r") as file:
    visual_prompts = file.read()

title = reel.get("title", "")
hook = reel.get("hook", "")
script = reel.get("script", "")

# Clean voiceover text

script = re.sub(
    r"\(Visual:.*?\)",
    "",
    script,
    flags=re.IGNORECASE | re.DOTALL
)

script = script.replace('"', "")
script = script.replace("\n", " ")
script = re.sub(r"\s+", " ", script).strip()

master_prompt = f"""
Create a professional cinematic Instagram Reel.

TITLE:
{title}

FORMAT:
- Vertical 9:16
- Instagram Reel
- 1080 x 1920
- Duration: 25 to 35 seconds

VISUAL STYLE:
- Photorealistic
- Cinematic
- High-end commercial quality
- Modern Indian corporate environment
- Premium storytelling
- Consistent visual style
- Realistic lighting
- No text inside visuals

VOICEOVER:

{hook}

{script}

VISUAL STORYBOARD:

{visual_prompts}

CAMERA STYLE:
- Slow cinematic camera movement
- Documentary-style visuals
- Smooth scene transitions
- Professional commercial cinematography
- Shallow depth of field

BACKGROUND MUSIC:
- Minimal cinematic piano
- Thought-provoking
- Modern corporate documentary feel
- No vocals
- Inspirational ending

SUBTITLES:
- Burned-in captions
- White modern typography
- Match voiceover timing

OUTPUT:
Generate a complete vertical Instagram Reel ready for publishing.
"""

output_file = os.path.join(
    "generated_videos",
    f"{reel_id}_master_prompt.txt"
)

with open(output_file, "w") as file:
    file.write(master_prompt)

print(
    f"Master video prompt saved to {output_file}"
)