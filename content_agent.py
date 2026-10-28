from ai_service import AIService, AIServiceError
from config_loader import (
    load_comedy_config,
    load_focus_thinkers,
    load_profile_story_settings,
    load_profile_subtypes,
    load_profile_thinkers,
    load_profile_visual_styles,
)
import json
import random
import re
from string import Template
import warnings

from profile_loader import load_profile
from project_paths import (
    GENERATED_POSTS_DIRECTORY,
    GENERATED_REELS_DIRECTORY,
    PROMPT_DIRECTORY,
)


PROMPT_TEMPLATE_PATH = PROMPT_DIRECTORY / "content_generation.md"
CAPTION_LANGUAGES = (
    "english", "hinglish", "hindi", "thai", "sinhala", "vietnamese",
    "burmese", "japanese", "chinese",
)
# Other languages add one line in their own script after the English hook.
_LANGUAGE_NAMES = {
    "hindi": "Hindi (Devanagari script)", "thai": "Thai (Thai script)",
    "sinhala": "Sinhala (Sinhala script)", "vietnamese": "Vietnamese",
    "burmese": "Burmese (Myanmar script)", "japanese": "Japanese",
    "chinese": "Chinese (simplified characters)",
}
VERIFIED_QUOTE_MODE = "verified_quote"



# Illustrated story modes: the image tool draws the words from the fields.
DESIGNED_IMAGE_RULES = (
    "This story mode is a finished illustrated design: the image tool will "
    "draw the words of Title, Main_point, and Supporting_copy into the "
    "picture. These rules replace the format's rules about a wordless image, "
    "an open upper third, and the 14-word Main_point limit:\n"
    "- Main_point may hold several lines, one item per line, as the "
    "structure describes.\n"
    "- Design_prompt describes only the illustration and where each piece of "
    "text sits (headline at the top, one row or panel per line, speech "
    "bubbles, and so on). Do not write the words themselves in "
    "Design_prompt; they are added from the other fields."
)

PLAIN_ENGLISH_RULES = (
    "Plain English (most important, for every on-screen line and the "
    "caption): write so a 12-year-old, or someone who learned English as a "
    "second language, understands it on the first read.\n"
    "- Use short, common words: \"sad\" not \"melancholy\", \"everyone\" not "
    "\"universal\", \"part\" not \"fragment\", \"change\" not "
    "\"transformation\", \"wanting\" not \"craving\".\n"
    "- Short sentences, about 12 words or fewer, one idea each.\n"
    "- No abstract or academic words (paradox, orientation, inherent, "
    "transaction, perspective, systemic, fallacy) and no idioms that do not "
    "translate.\n"
    "- Say what happens in real life (\"you check your phone again\") rather "
    "than naming a concept.\n"
    "- A Pali or Sanskrit word may appear once, followed by its simple "
    "meaning, for example \"metta (loving-kindness)\".\n"
    "- Verified quotes stay exactly as written; explain them simply in the "
    "caption instead.\n\n"
)

class ContentAgent:

    def __init__(
        self,
        profile_id="rational_thoughts",
        profile=None,
        brand=None,
        content_format=None,
        platform=None,
        brief=None,
        brand_identity_explicit=False,
        brand_selected=True,
        category_id=None,
        comedy_subtype=None,
        subtype=None,
        qa_subtype=None,
        thinker_id=None,
        visual_style=None,
        caption_language="english",
        scenery=None,
        weather=None,
        hashtag_count=None,
        life_scene=None,
        recent_moments=None,
        video=False,
    ):
        self.ai_service = AIService()
        self.video = video
        self.hashtag_count = hashtag_count
        self.life_scene = life_scene
        self.recent_moments = recent_moments or []
        self.scenery = scenery
        self.weather = weather
        self.profile = profile or load_profile(profile_id)
        self.brand = brand
        self.content_format = content_format
        self.platform = platform
        self.brief = brief
        self.brand_identity_explicit = brand_identity_explicit
        self.brand_selected = brand_selected
        self.category_id = category_id
        self.comedy_subtype = comedy_subtype
        self.subtype = subtype or qa_subtype  # legacy keyword
        self.thinker_id = thinker_id
        self.visual_style = visual_style
        if caption_language not in CAPTION_LANGUAGES:
            raise ValueError(f"Unknown caption language {caption_language!r}.")
        self.caption_language = caption_language

    def get_previous_titles(self, profile_id=None, brand_id=None):

        titles = []
        selected_profile_id = profile_id or self.profile["id"]
        selected_brand_id = (
            brand_id
            if brand_id is not None
            else (
                getattr(self.brand, "id", "default")
                if self.brand_selected
                else None
            )
        )
        content_files = []
        for folder in (
            GENERATED_REELS_DIRECTORY,
            GENERATED_POSTS_DIRECTORY,
        ):
            if folder.exists():
                content_files.extend(folder.glob("*.json"))

        for file_path in sorted(content_files):
            try:
                with file_path.open(encoding="utf-8") as reel_file:
                    reel = json.load(reel_file)
            except (OSError, json.JSONDecodeError) as error:
                warnings.warn(
                    f"Skipping unreadable content record {file_path}: {error}",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue

            if not isinstance(reel, dict):
                warnings.warn(
                    f"Skipping invalid content record {file_path}: expected a "
                    "JSON object.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue

            record_profile_id = reel.get("profile_id", "rational_thoughts")
            record_brand_id = reel.get("brand_id", "default")
            title = reel.get("title")
            if (
                record_profile_id == selected_profile_id
                and record_brand_id == selected_brand_id
                and title
            ):
                titles.append(title)

        return titles[-10:]

    def generate_content(self):
        """Assemble the prompt from its sections and call the model.

        Each section returns text to place before what is already built (or
        an empty string), so later sections appear earlier in the prompt.
        """
        self._story_settings = load_profile_story_settings(self.profile["id"])
        prompt = self._base_prompt()
        for section in (
            self._brand_section,
            self._format_section,
            self._duration_section,
            self._thinker_section,
            self._lens_section,
            self._visual_style_section,
            self._setting_section,
            self._subtype_section,
            self._comedy_section,
            self._caption_language_section,
            self._plain_english_section,
            self._brief_section,
        ):
            prompt = section() + prompt
        return self.ai_service.generate_reel(
            prompt + self._designed_reminder() + self._hashtag_reminder()
            + self._brief_reminder() + self._life_scene_reminder()
            + self._video_reminder()
        )

    def _base_prompt(self):
        previous_titles = self.get_previous_titles()
        profile = self.profile
        prompt_template_path = PROMPT_TEMPLATE_PATH
        format_template = getattr(self.content_format, "prompt_template", None)
        if format_template:
            prompt_template_path = PROMPT_DIRECTORY / "formats" / format_template
        with prompt_template_path.open(encoding="utf-8") as prompt_file:
            prompt_template = Template(prompt_file.read())
        return prompt_template.substitute(
            display_name=profile["display_name"],
            audience=profile["audience"]["description"],
            language=profile["language"],
            objectives=_as_bullets(profile["objectives"]),
            voice_traits=", ".join(profile["voice"]["traits"]),
            voice_avoid=", ".join(profile["voice"]["avoid"]),
            topics=_as_bullets(profile["topics"]),
            previous_titles=_as_bullets(previous_titles)
            if previous_titles
            else "- None",
        )

    def _brand_section(self):
        profile = self.profile
        brand_traits = getattr(self.brand, "voice_traits", ())
        brand_avoid = getattr(self.brand, "voice_avoid", ())
        brand_name = getattr(self.brand, "display_name", None)
        show_brand_identity = (
            self.brand is not None
            and (
                getattr(self, "brand_identity_explicit", False)
                or profile["id"] == getattr(self.brand, "default_profile_id", None)
            )
        )
        brand_context = []
        if show_brand_identity and brand_name and brand_name != profile["display_name"]:
            brand_context.append(f"Publishing brand: {brand_name}")
        if show_brand_identity and brand_traits:
            brand_context.append(
                "Brand voice traits: " + ", ".join(brand_traits)
            )
        if show_brand_identity and brand_avoid:
            brand_context.append("Brand voice to avoid: " + ", ".join(brand_avoid))
        return "\n".join(brand_context) + "\n\n" if brand_context else ""

    def _format_section(self):
        format_instructions = getattr(self.content_format, "instructions", ())
        if not format_instructions:
            return ""
        instructions = "\n".join(
            f"- {instruction}" for instruction in format_instructions
        )
        return f"Selected format requirements:\n{instructions}\n\n"

    def _duration_section(self):
        format_id = getattr(self.content_format, "id", "reel")
        duration = self._story_settings["reel_duration_seconds"]
        if not (duration and format_id == "reel" and self.category_id != "comedy"):
            return ""
        return (
            f"Recommended duration: {duration['minimum']}-"
            f"{duration['maximum']} seconds. Pace the script for about "
            f"{duration['minimum'] * 5 // 2}-{duration['maximum'] * 5 // 2} "
            "spoken words and land the hook within the first 1-2 seconds.\n"
            "In the script, mark each visual beat with a strong, specific "
            "background: setting, lighting, color mood, and a short "
            "background-music cue.\n\n"
        )

    def _thinker_section(self):
        profile = self.profile
        if not self.thinker_id:
            if self.category_id == "comedy":
                return ""
            thinkers = load_focus_thinkers(profile["id"])
            if not thinkers:
                return ""
            return (
                "Build the story on one real idea from one of these "
                "thinkers: "
                + ", ".join(item["name"] for item in thinkers)
                + ". Draw on the full range of their teaching, not one "
                "favorite text. Paraphrase rather than invent quotations "
                "and name the teaching and its reference in the "
                "caption.\n\n"
            )
        thinker = next(
            (
                item
                for item in load_profile_thinkers(profile["id"])
                if item["id"] == self.thinker_id
            ),
            None,
        )
        if thinker is None:
            raise ValueError(
                f"Unknown thinker {self.thinker_id!r} for "
                f"profile {profile['id']!r}."
            )
        quote_mode = self.subtype == VERIFIED_QUOTE_MODE
        quote = (
            random.choice(thinker["quotes"])
            if quote_mode and thinker.get("quotes")
            else None
        )
        # A random pick keeps drafts from collapsing onto the first idea.
        focus_idea = random.choice(thinker["core_ideas"])
        thinker_lines = [
            f"Selected thinker: {thinker['name']}"
            + (f" ({thinker['era']})" if thinker.get("era") else ""),
            f"Build this draft on this core idea: {focus_idea}",
            "Other core ideas (for context only):",
            _as_bullets(
                [idea for idea in thinker["core_ideas"] if idea != focus_idea]
            ),
            "Verified sources:",
            _as_bullets(thinker["sources"]),
        ]
        if thinker.get("misattributions"):
            thinker_lines += [
                "Misattributed quotes to avoid (never present these as "
                "the thinker's words):",
                _as_bullets(thinker["misattributions"]),
            ]
        scenes = thinker.get("life_scenes") or []
        chosen = next((scene for scene in scenes if scene["id"] == self.life_scene), None)
        if chosen:
            thinker_lines += [
                "Tell this moment from his life:",
                f"- Moment: {chosen['episode']} ({chosen['source']}).",
                f"- Scene for the Design_prompt, with everyone in it: {chosen['scene']}.",
                f"- Lesson: {chosen['teaching']}.",
                "On screen, tell the moment itself, not a general \"you\" line: "
                "Main_point says who and what happens (for example \"A bandit "
                "with a sword chases the Buddha.\"); Supporting_copy says what "
                "the Buddha did or said and the lesson. The caption can then "
                "speak to the viewer.",
            ]
        elif self.subtype == "life_story":
            thinker_lines += [
                "Choose one true moment from anywhere in his life, not only "
                "the famous ones: his birth at Lumbini, the four sights, "
                "leaving the palace, the years of hard practice, the "
                "awakening, his teachings and the people he met, his family, "
                "the monks and nuns, kings and outcasts, animals, and his "
                "last days and passing at Kusinara.",
                "Name the source in the caption. If the moment comes from "
                "later biographies or legend (for example the seven steps "
                "at birth) rather than the early suttas, say \"tradition "
                "says\" instead of presenting it as history.",
                "On screen, tell the moment itself, not a general \"you\" "
                "line: Main_point says who and what happens; Supporting_copy "
                "says what the Buddha did or said and the lesson.",
            ]
            if self.recent_moments:
                thinker_lines += [
                    "Recently told; pick a different moment:",
                    _as_bullets(self.recent_moments),
                ]
        elif scenes:
            # Show him among people, not always alone or with one monk.
            thinker_lines.append(
                "In the Design_prompt, when it fits the post, show him with "
                "other people rather than alone: a few monks walking behind "
                "him, villagers listening, someone offering food, or a moment "
                "from his life such as "
                + "; ".join(scene["episode"] for scene in random.sample(scenes, min(4, len(scenes))))
                + "."
            )
        if thinker.get("portrayal"):
            thinker_lines.append(f"Portrayal: {thinker['portrayal']}")
        if thinker.get("setting"):
            thinker_lines.append(f"Period background: {thinker['setting']}")
        if thinker.get("art_alias"):
            thinker_lines.append(
                "Image tools refuse to draw this thinker by name: if they "
                "appear in the image, call them "
                f"'{thinker['art_alias']}' in the Design_prompt, never "
                "by name, and do not describe their face."
            )
        else:
            thinker_lines.append(
                "If the thinker appears in the image, name them in the "
                "Design_prompt subject (for example "
                f"'{thinker['name'].split(' (')[0]} in his later years') "
                "instead of describing their face."
            )
        thinker_lines.append(
            "Paraphrase the idea instead of inventing quotations. Quote "
            "only wording you are confident appears in a listed source. "
            "In the caption, name the teaching and the reference given "
            "with the idea, for example 'Teaching: The Second Arrow "
            "(SN 36.6)'. Label later-tradition ideas by their tradition "
            "(for example 'Zen story'), never as the Buddha's own words.\n\n"
        )
        if quote:
            thinker_lines.insert(
                0,
                "Verified quote to use (copy the wording exactly, in "
                f"quotation marks, as Main_point): \"{quote['text']}\"\n"
                f"Supporting_copy must be: — {_short_name(thinker)}, "
                f"{quote['source']}\n"
                f"In the caption, write 'Source: {quote['source']}'.",
            )
        elif not quote_mode and thinker.get("quotes"):
            options = "\n".join(
                f"- \"{item['text']}\" ({item['source']})"
                for item in thinker["quotes"]
            )
            thinker_lines.append(
                "Verified quotes (the only words you may put in quotation "
                f"marks or credit as '— {_short_name(thinker)}'; use one "
                "verbatim if it fits):\n" + options + "\nAnything else "
                f"must be credited as '— inspired by {_short_name(thinker)}'."
            )
        elif quote_mode:
            thinker_lines.insert(
                0,
                "No verified quote is on file for this thinker. Do not "
                "quote them: paraphrase one core idea in your own words "
                f"and set Supporting_copy to '— inspired by {_short_name(thinker)}'.",
            )
        return "\n".join(thinker_lines)

    def _lens_section(self):
        lens = self._story_settings.get("critical_lens") or []
        if not lens or self.category_id == "comedy":
            return ""
        return (
            "Critical-thinking lens (apply it to every concept):\n"
            + _as_bullets(lens)
            + "\n\n"
        )

    def _visual_style_section(self):
        if not self.visual_style:
            return ""
        profile = self.profile
        style = next(
            (
                item
                for item in load_profile_visual_styles(profile["id"])
                if item["id"] == self.visual_style
            ),
            None,
        )
        if style is None:
            raise ValueError(f"Unknown visual style {self.visual_style!r}.")
        return (
            f"Visual style for the Design_prompt: {style['name']}. "
            f"{style['recipe'].strip()}\n"
            "Write the scene so it suits this style, but do not repeat the "
            "style keywords; they are added automatically. Show revered "
            "religious and spiritual figures (for example the Buddha, "
            "Kabir, or Vivekananda) with dignity: in comedy or scenes with "
            "modern gadgets, use an anonymous stand-in instead.\n\n"
        )

    def _setting_section(self):
        """The place and weather for the art, rotated across posts."""
        from config_loader import load_profile_sceneries, load_profile_weathers

        lines = []
        for value, loader, label in (
            (self.scenery, load_profile_sceneries, "Place"),
            (self.weather, load_profile_weathers, "Weather and light"),
        ):
            if not value:
                continue
            item = next(
                (entry for entry in loader(self.profile["id"]) if entry["id"] == value),
                None,
            )
            if item is None:
                raise ValueError(f"Unknown {label.lower()} {value!r}.")
            lines.append(f"- {label}: {item['description']}.")
        if not lines:
            return ""
        return (
            "Setting for the Design_prompt (use it instead of the thinker's "
            "usual setting or golden light; keep the story and subject):\n"
            + "\n".join(lines)
            + "\n\n"
        )

    def _subtype_section(self):
        if not self.subtype:
            return ""
        profile = self.profile
        story_settings = self._story_settings
        selected_subtype = next(
            (
                subtype
                for subtype in load_profile_subtypes(profile["id"])
                if subtype["id"] == self.subtype
            ),
            None,
        )
        if selected_subtype is None:
            raise ValueError(
                f"Unknown subtype {self.subtype!r} for "
                f"profile {profile['id']!r}."
            )
        label = story_settings["subtype_label"]
        subtype_lines = [
            f"Selected {label}: {selected_subtype['name']} — "
            f"{selected_subtype['definition']}"
        ]
        for key, heading in (
            ("structure", "Structure"),
            ("background", "Background and music"),
            ("example", "Example of the approach (do not copy)"),
        ):
            if selected_subtype.get(key):
                subtype_lines.append(f"{heading}: {selected_subtype[key]}")
        if selected_subtype.get("designed_image") and not self._is_carousel():
            subtype_lines.append(DESIGNED_IMAGE_RULES)
        subtype_lines.append(
            f"Focus the content on this {label.lower()} while preserving the "
            "selected format's fields and the profile's accuracy safeguards.\n\n"
        )
        return "\n".join(subtype_lines)

    def _hashtag_reminder(self):
        """Override the formats' "exactly 5 hashtags" (used to test fewer)."""
        if self.hashtag_count is None or self.hashtag_count == 5:
            return ""
        if self.hashtag_count == 0:
            return (
                "\n\nHashtags: use NO hashtags in this caption. Instead make sure "
                "the first line and the source line carry the words people "
                "search for.\n"
            )
        return (
            f"\n\nHashtags: use exactly {self.hashtag_count} hashtags (not 5), the "
            "most relevant first: #Buddhism, then the source or tradition tag, "
            "then #Mindfulness.\n"
        )

    def _is_carousel(self):
        return getattr(self.content_format, "id", None) == "carousel"

    def _designed_reminder(self):
        """Restate an illustrated story mode's fields after the format rules,
        which otherwise win (a small model follows the last instructions)."""
        if not self.subtype:
            return ""
        selected = next(
            (
                item
                for item in load_profile_subtypes(self.profile["id"])
                if item["id"] == self.subtype and item.get("designed_image")
            ),
            None,
        )
        if selected is None:
            return ""
        if self._is_carousel():
            # In a carousel the app draws the slides: the list goes one item
            # per slide, not into Main_point, and the art is a wordless cover.
            return (
                f"\n\nIMPORTANT: this is a {selected['name']} written as a carousel. "
                "Keep the carousel's sections. Title is the cover headline; "
                "Main_point is one short line under it on the cover (at most 12 "
                "words, not a list); Slides holds the items, ONE per line, in "
                "order (numbered like \"1. ...\" when it is a list); "
                "Supporting_copy is the closing slide. Design_prompt is a "
                "wordless cover scene, not an illustrated page. Shape to follow: "
                f"{' '.join(selected['structure'].split())}\n"
            )
        return (
            f"\n\nIMPORTANT, this overrides the format rules above: this is a "
            f"{selected['name']} post. Write Title, Main_point, and "
            f"Supporting_copy exactly as this structure says, not as a "
            f"\"For the ...\" hook: {' '.join(selected['structure'].split())}\n"
            f"Example of the shape (do not copy): {selected.get('example', '')}\n"
            "Design_prompt: describe the illustrated page as one paragraph of "
            "60-110 words (where the headline sits, one drawing or panel per "
            "line or bubble, what each drawing shows, the background), without "
            "Subject/Pose/Shot labels, without reserving empty space for text, "
            "and without writing the words themselves.\n"
        )

    def _comedy_section(self):
        if self.category_id != "comedy":
            return ""
        comedy = load_comedy_config()
        subtypes = comedy["subtypes"]
        selected_subtype = next(
            (
                subtype
                for subtype in subtypes
                if subtype["id"] == self.comedy_subtype
            ),
            None,
        )
        subtype_guidance = (
            f"Subtype: {selected_subtype['name']} — "
            f"{selected_subtype['definition']}\n"
            if selected_subtype
            else (
                "Choose one subtype for the brief: "
                + ", ".join(subtype["name"] for subtype in subtypes)
                + ".\n"
            )
        )
        format_id = getattr(self.content_format, "id", "reel")
        brand_id = getattr(self.brand, "id", None)
        brand_name = getattr(self.brand, "display_name", None)
        publishing_identity = (
            f"Publishing brand: {brand_name}\n"
            if brand_id == comedy["brand_id"]
            and format_id != "linkedin_text_post"
            and brand_name
            else ""
        )
        format_config = comedy["formats"][format_id]
        duration = format_config.get("default_duration_seconds", {})
        duration_guidance = (
            f"Recommended duration: {duration['minimum']}-"
            f"{duration['maximum']} seconds.\n"
            if duration
            else ""
        )
        if format_id == "reel":
            format_guidance = (
                "Reel: immediate hook, visual setup, escalation, "
                "surprise, concise punchline. Preserve existing fields."
            )
        elif format_id == "single_page":
            format_guidance = (
                "Single page: one glance-readable visual joke on the "
                "configured 4:5 canvas. Use only supplied copy and labels."
            )
        else:
            format_guidance = (
                "LinkedIn: preserve professional accuracy and the existing "
                "fields; do not apply Life Is a Glitch branding."
            )
        comedy_guidance = (
            f"COMEDY ({comedy['audience']}): "
            f"{', '.join(comedy['tone'])}. "
            f"{subtype_guidance}"
            f"Topics: {', '.join(comedy['topics'])}. "
            f"Avoid: {', '.join(comedy['avoid'])}. "
            f"{format_guidance}\n"
            f"{duration_guidance}"
            "Quality check: clear setup, original joke, strong punchline, "
            "visually practical. Return only the selected format's fields.\n\n"
        )
        return comedy_guidance

    def _caption_language_section(self):
        if self.caption_language in _LANGUAGE_NAMES:
            return (
                "Caption language: after the caption's English hook line, add "
                f"one short, natural line in {_LANGUAGE_NAMES[self.caption_language]} "
                "that restates the idea warmly for readers of that language. "
                "Keep every other caption line and all on-screen copy in "
                "English, and keep the whole caption under 450 characters.\n\n"
            )
        if self.caption_language != "hinglish":
            return ""
        return (
            "Caption language: after the caption's English hook line, add "
            "one short, natural Hinglish line (Hindi written in Latin "
            "script, the way people text in India) that restates the "
            "idea warmly. Keep every other caption line and all on-screen "
            "copy in English.\n\n"
        )

    def _plain_english_section(self):
        # Many viewers read English as a second language; plain words reach
        # them, and the wider audience the page is aiming for.
        return PLAIN_ENGLISH_RULES

    def _video_reminder(self):
        """A video Reel's scene is filmed as one 10-second shot, so it needs a
        moment with gentle movement rather than a frozen pose."""
        if not self.video:
            return ""
        return (
            "\n\nIMPORTANT: this Reel is a 10-second video clip, not a still. "
            "The Design_prompt describes one continuous moment with gentle, "
            "natural movement that a single slow shot can show: someone "
            "walking slowly, pouring water, offering food, lighting a lamp, "
            "breathing in meditation, leaves falling, rain on a pond, mist "
            "drifting. Name what moves. Keep the Buddha calm and still in "
            "body; no running, fighting, crowds, or sudden action. Frame it as a "
            "wide or medium shot with the figure in the lower half; never a "
            "close-up or a push toward a face (the words sit in the upper "
            "third). No words, letters, or signs anywhere in the scene.\n"
        )

    def _life_scene_reminder(self):
        """Restate the chosen life moment last, so it wins over the format's
        general voice."""
        if not self.life_scene or not self.thinker_id:
            return ""
        thinker = next(
            (item for item in load_profile_thinkers(self.profile["id"]) if item["id"] == self.thinker_id),
            None,
        )
        scene = next(
            (item for item in (thinker or {}).get("life_scenes", []) if item["id"] == self.life_scene),
            None,
        )
        if scene is None:
            return ""
        return (
            f"\n\nIMPORTANT: this post tells one moment: {scene['episode']} "
            f"({scene['source']}). Main_point says who and what happens in that "
            "moment (not a general \"you\" line); Supporting_copy says what the "
            f"Buddha did or said and the lesson ({scene['teaching']}). The "
            f"Design_prompt shows exactly this scene with everyone in it: "
            f"{scene['scene']}.\n"
        )

    def _brief_reminder(self):
        """Restate the brief last: a small model follows the final
        instructions, and the brief's topic must decide the post."""
        if not self.brief:
            return ""
        reminder = (
            "\n\nIMPORTANT: the post's topic comes from this brief; keep the "
            "story mode's shape, but make every line about it:\n"
            f"{self.brief.strip()}\n"
        )
        if self.brief.strip().startswith("Occasion:"):
            reminder += (
                "Main_point (the first line people see; the title is often "
                "hidden) must name the day, for example \"Tomorrow is the full "
                "moon.\" or \"Today is Pavarana.\"; Supporting_copy gives the "
                "teaching or the way to observe it. The caption must say in one "
                "plain line what the day is and give one way to observe it, "
                "before the source line. The Design_prompt must show the day "
                "and the practice the post suggests (for example a bright full "
                "moon over a temple with someone meditating), not a generic "
                "figure.\n"
            )
        return reminder

    def _brief_section(self):
        if not self.brief:
            return ""
        return (
            f"Generation brief:\n{self.brief.strip()}\n\n"
            "Follow the profile and format requirements below.\n\n"
        )

    def shorten_caption(self, caption, limit):
        """Ask the model for a shorter caption that keeps sources and tags."""
        prompt = (
            f"Shorten this Instagram caption to under {limit - 50} characters, "
            "hashtags included. Keep any line starting with 'Teaching:' or "
            "'Source:' exactly as written, keep the hashtags exactly, keep one "
            "closing question, and keep the meaning honest. Return only the "
            "caption.\n\n" + caption
        )
        return self.ai_service.generate_reel(prompt).strip()


VIDEO_SCRIPT_BEATS = (
    ("Opening", "0-3 s"),
    ("Middle", "3-7 s"),
    ("Ending", "7-10 s"),
)


def _plain(text):
    return re.sub(r"\*\*(.+?)\*\*", r"\1", str(text or "")).strip()


def write_video_script(record, ai_service=None):
    """Plan a 10-second Google Flow clip for a video Reel, beat by beat.

    Returns the script as labelled lines (shown on the Content tab and used
    for the Flow prompt). The words on screen are timed by the renderer, so
    the model plans only what is seen and heard.
    """
    hook, payoff = _plain(record.get("main_point")), _plain(record.get("supporting_copy"))
    prompt = (
        "Plan one continuous 10-second vertical video shot for an Instagram "
        "Reel about a Buddhist teaching. It will be made with Google Veo, "
        "so describe only what the camera sees and hears.\n\n"
        f"Hook line on screen from 0 s: {hook}\n"
        f"Payoff line on screen from 3.5 s: {payoff}\n"
        f"Scene: {record.get('design_prompt', '')}\n\n"
        "Rules: one shot, no cuts. Gentle, natural movement only, and say "
        "exactly what moves (a hand, a lamp flame, robes, water, leaves, "
        "mist, slow footsteps). The Buddha, if present, stays calm and "
        "dignified: no big gestures, no laughing. The movement should echo "
        "the lines (for example, the payoff moment arrives as a lamp is lit "
        "or a hand opens). No words, letters, or signs in the scene. No "
        "speech or music.\n\n"
        "Reply with exactly these five lines and nothing else:\n"
        "Opening: what we see and what moves, 0-3 s (one sentence)\n"
        "Middle: what changes, 3-7 s (one sentence)\n"
        "Ending: a calm ending that could loop back, 7-10 s (one sentence)\n"
        "Camera: one slow camera move that keeps the whole figure in frame "
        "and the head below the middle of the frame, for example a slow "
        "sideways drift or a very slight push; never a close-up or a zoom "
        "toward a face (one short sentence)\n"
        "Sound: two or three natural sounds, no speech or music\n"
    )
    reply = (ai_service or AIService()).generate_reel(prompt)
    found = {}
    for label in ("Opening", "Middle", "Ending", "Camera", "Sound"):
        match = re.search(rf"^\W*{label}\W*[:\-]\s*(.+)$", reply, re.IGNORECASE | re.MULTILINE)
        if match:
            found[label] = match.group(1).strip().strip("*").strip()
    if not all(label in found for label, _ in VIDEO_SCRIPT_BEATS):
        raise AIServiceError("The model did not return a usable video script.")
    cta = _plain(record.get("cta"))
    lines = [
        f"{label} ({span}): {found[label]}"
        + (f" On screen: \"{hook}\"" if label == "Opening" and hook else "")
        + (f" On screen from 3.5 s: \"{payoff}\"" if label == "Middle" and payoff else "")
        for label, span in VIDEO_SCRIPT_BEATS
    ]
    if cta:
        lines.append(f"Closing card (10-12 s): \"{cta}\"")
    lines.append(f"Camera: {found.get('Camera') or 'One slow, steady push-in.'}")
    lines.append(f"Sound: {found.get('Sound') or 'Soft natural ambience.'}")
    return "\n".join(lines)


# How many alternative hooks to ask for, and how much better (in hook_score
# points) one must be to replace the generated hook.
HOOK_OPTION_COUNT = 5
HOOK_SWAP_MARGIN = 8
# Story modes whose hook cannot be swapped: the quote under test, the exact
# quote, the young monk's line, words painted into the art, and two-part
# lines whose payoff finishes the hook's sentence.
FIXED_HOOK_MODES = {
    "real_or_fake", "verified_quote", "dialogue", "mirror", "one_liner",
    "mind_states", "numbered_list", "illustrated_metaphor", "parable_card",
}


def _hook_is_fixed(record):
    mode = record.get("subtype") or record.get("qa_subtype")
    payoff = _plain(record.get("supporting_copy"))
    # A payoff starting in lower case finishes the hook's sentence.
    return mode in FIXED_HOOK_MODES or bool(payoff[:1].islower())


def write_hook_options(record, ai_service=None, count=HOOK_OPTION_COUNT):
    """Ask for alternative on-screen hooks (Main_point), one per formula.

    Returns (formula id, hook line) pairs. Verified quotes keep their
    words, so they get none.
    """
    from hook_score import formula_example, formulas_for, hook_rules

    if _hook_is_fixed(record):
        return []
    profile_id = record.get("profile_id")
    formulas = formulas_for(profile_id)
    hook, payoff = _plain(record.get("main_point")), _plain(record.get("supporting_copy"))
    life_story = record.get("subtype") == "life_story"
    prompt = (
        "Write alternative opening lines (hooks) for a 10-second Instagram "
        "Reel. The hook is shown alone for the first seconds; the payoff "
        "line appears after it.\n\n"
        f"Current hook: {hook}\n"
        f"Payoff (do not give it away): {payoff}\n"
        f"Teaching and source, from the caption: {_plain(record.get('caption'))[:600]}\n\n"
        "Hook formulas (name, shape, example):\n"
        + "".join(
            f"- {formula['id']}: {formula['shape']} Example: {formula_example(formula, profile_id)}\n"
            for formula in formulas
        )
        + "\nRules:\n"
        + _as_bullets(hook_rules())
        + "\n- At most 14 words, plain everyday English.\n"
        "- Wrap one or two key words in **double asterisks**.\n"
        "- Each hook uses a different formula and must still lead to the payoff above.\n"
        "- Keep the same teaching and source; never invent a number, quote, or source.\n"
        + ("- Tell the moment itself: who and what happens in the story.\n" if life_story else "")
        + f"\nReply with exactly {count} lines, each as: formula-id | hook\n"
    )
    reply = (ai_service or AIService()).generate_reel(prompt)
    known = {formula["id"] for formula in formulas}
    options = []
    for line in reply.splitlines():
        if "|" not in line:
            continue
        formula_id, text = (part.strip().strip("*-").strip() for part in line.split("|", 1))
        text = text.strip().strip('"').strip()
        if text.count("**") % 2:
            text = text.replace("**", "")  # an unclosed highlight would show
        if text and formula_id.lower() in known and len(_plain(text).split()) <= 18:
            options.append((formula_id.lower(), text))
    if not options:
        raise AIServiceError("The model did not return usable hooks.")
    return options[:count]


def choose_hook(record, options, margin=HOOK_SWAP_MARGIN):
    """Score the current hook and the options; returns (main_point, scored).

    The best option replaces the current hook only when it is clearly
    better, so a good generated hook is not churned for a tiny gain.
    """
    from hook_score import formulas_for, score_hook

    current = record.get("main_point") or ""
    formulas = formulas_for(record.get("profile_id"))
    names = {formula["id"]: formula["name"] for formula in formulas}
    scored = []
    for index, option in enumerate([(None, current), *options]):
        stated, text = option if isinstance(option, tuple) else (None, option)
        if not _plain(text):
            continue
        item = score_hook(text, formulas)
        if stated in names:
            # The formula the model wrote it with beats a regex guess.
            item.update(formula=stated, formula_name=names[stated])
        item.update(text=text, original=index == 0)
        scored.append(item)
    scored.sort(key=lambda item: -item["verdict"])
    best = scored[0] if scored else None
    original = next((item for item in scored if item["original"]), None)
    if best and original and not best["original"] and best["verdict"] - original["verdict"] >= margin:
        return best["text"], scored
    return current, scored


def apply_hook_options(record, ai_service=None):
    """Add scored hook options to a new draft and use the best hook.

    Saves ``hook_options`` (best first) and ``hook_formula``; an AI failure
    keeps the generated hook. Multi-line hooks (lists carried by the art)
    and verified quotes are left alone.
    """
    hook = str(record.get("main_point") or "")
    if not hook.strip() or "\n" in hook.strip() or _hook_is_fixed(record):
        return record
    try:
        options = write_hook_options(record, ai_service=ai_service)
    except AIServiceError:
        options = []
    chosen, scored = choose_hook(record, options)
    record["main_point"] = chosen
    record["hook_options"] = [
        {key: item[key] for key in ("text", "verdict", "band", "formula", "formula_name", "fix", "original")}
        for item in scored
    ]
    picked = next((item for item in scored if item["text"] == chosen), None)
    if picked and picked["formula"]:
        record["hook_formula"] = picked["formula"]
    return record


def _short_name(thinker):
    """'The Buddha (Siddhartha Gautama)' -> 'The Buddha' for on-screen credits."""
    return thinker["name"].split(" (")[0]


def _as_bullets(values):
    return "\n".join(f"- {value}" for value in values)


SIMPLIFY_FIELDS = ("title", "main_point", "supporting_copy", "caption")
_SIMPLIFY_LABELS = {
    "Title": "title",
    "Main_point": "main_point",
    "Supporting_copy": "supporting_copy",
    "Caption": "caption",
}


def simplify_copy(record, ai_service=None, fresh=False):
    """Suggest plain-English versions of a post's text; nothing is saved.

    With ``fresh``, write new wording (a different hook and line) on the
    same teaching instead of simplifying the current lines.

    Exact quotes ("verified_quote" posts) and credit lines ("— the Buddha")
    are kept as written; only the wording around them changes.
    """
    keep_quote = (record.get("subtype") or record.get("qa_subtype")) == "verified_quote"
    current = {field: str(record.get(field) or "").strip() for field in SIMPLIFY_FIELDS}
    keep_credit = current["supporting_copy"].startswith(("—", "-", "–"))
    task = (
        "Write fresh text for this Instagram post in plain English for a wide "
        "audience: a new hook and a new main line about the same teaching "
        "and source, with a real-life example in the caption. Do not reuse "
        "the current lines.\n\n"
        if fresh
        else "Rewrite this Instagram post's text in plain English for a wide "
        "audience. Keep the same meaning, teaching, and tone; change only "
        "the wording.\n\n"
    )
    prompt = (
        task
        + PLAIN_ENGLISH_RULES
        + "Rules for the rewrite:\n"
        "- Title: 2-5 plain words.\n"
        "- Main_point: at most 14 words. It is shown alone first, as the hook: "
        "raise the question or tension, but do not give the answer.\n"
        "- Supporting_copy appears a few seconds later as the payoff that "
        "answers or turns the hook.\n"
        "- Supporting_copy: at most 12 words.\n"
        "- Wrap one to three key words in Title, Main_point, and "
        "Supporting_copy in **double asterisks**.\n"
        + ("- Keep Main_point exactly as written (it is a verified quote).\n" if keep_quote else "")
        + ("- Keep Supporting_copy exactly as written (it is a credit).\n" if keep_credit else "")
        + "- Caption: keep any line starting with 'Teaching:', 'Source:', or "
        "'Idea:' exactly, keep the hashtags exactly, keep the same parts in "
        "the same order, and stay under 450 characters.\n\n"
        "Current text:\n"
        + "".join(f"{label}: {current[field]}\n" for label, field in _SIMPLIFY_LABELS.items())
        + "\nReturn exactly these four sections and nothing else:\n"
        "Title:\nMain_point:\nSupporting_copy:\nCaption:\n"
    )
    reply = (ai_service or AIService()).generate_reel(prompt)
    suggestion = _parse_simplified(reply)
    if keep_quote:
        suggestion["main_point"] = current["main_point"]
    if keep_credit:
        suggestion["supporting_copy"] = current["supporting_copy"]
    # Fall back to the current text for anything the model left out.
    return {field: suggestion.get(field) or current[field] for field in SIMPLIFY_FIELDS}


def _parse_simplified(reply):
    labels = "|".join(_SIMPLIFY_LABELS)
    parts = re.split(rf"^\s*\**({labels})\**\s*:", str(reply), flags=re.MULTILINE)
    found = {}
    for label, text in zip(parts[1::2], parts[2::2]):
        text = text.strip()
        if label != "Caption":
            # Keep one item per line (list posts), tidy spaces within lines.
            text = "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
        found[_SIMPLIFY_LABELS[label]] = text
    return found
