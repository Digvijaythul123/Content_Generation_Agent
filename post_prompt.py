from content_text import strip_highlights


def build_ready_design_prompt(
    fields, content_format, platform, category_id=None
):
    required_fields = (
        "title",
        "main_point",
        "supporting_copy",
        "visual_labels",
        "design_prompt",
    )
    missing_fields = [
        field
        for field in required_fields
        if not isinstance(fields.get(field), str) or not fields[field].strip()
    ]
    if missing_fields:
        raise ValueError(
            "Cannot create a ready-to-use design prompt; missing content: "
            + ", ".join(missing_fields)
        )
    if content_format.content_kind != "post":
        raise ValueError(
            "A ready-to-use post design prompt requires a post content format."
        )

    dimensions = content_format.resolution or "format appropriate"
    aspect_ratio = content_format.aspect_ratio or "unspecified"
    visual_labels = fields["visual_labels"].strip()
    diagram_label_section = (
        "\n\nEXACT DIAGRAM LABELS TO INCLUDE:\n"
        f"{visual_labels}"
        if visual_labels.casefold() != "none"
        else ""
    )
    comedy_direction = (
        "\n\nCOMEDY VISUAL DIRECTION:\n"
        "Make the visual reinforce the selected joke through a clear, "
        "readable visual situation. Choose a visual approach that serves "
        "the joke. Do not add any wording beyond the exact copy and labels "
        "specified above."
        if category_id == "comedy"
        else ""
    )
    return (
        f"Create one finished {platform.display_name} social media graphic.\n"
        f"Canvas: {aspect_ratio} portrait; {dimensions}.\n\n"
        "VISUAL DESIGN DIRECTION:\n"
        f"{fields['design_prompt'].strip()}\n\n"
        "EXACT COPY TO INCLUDE IN THE IMAGE:\n"
        f"Headline: {strip_highlights(fields['title']).strip()}\n"
        f"Main point: {strip_highlights(fields['main_point']).strip()}\n"
        f"Supporting copy: {strip_highlights(fields['supporting_copy']).strip()}"
        f"{diagram_label_section}{comedy_direction}\n\n"
        "Render the supplied copy verbatim: preserve spelling, punctuation, "
        "capitalization, and wording. Include only the exact diagram labels "
        "listed above when that section is present. Do not add, omit, repeat, "
        "paraphrase, or invent any other text, labels, numbers, or logos. "
        "Label every diagram node clearly and connect labels to the correct "
        "nodes. Arrange the copy in a clear, readable hierarchy with "
        "sufficient contrast and spacing. "
        "Keep all text inside the canvas safe area. Do not include the caption. "
        "The finished image must communicate the idea without relying on "
        "unprovided words."
    )


def build_post_prompt_file(
    record, content_format, platform, category_id=None, art_style=None
):
    """Return the prompt saved beside a post for use in an image tool.

    One-image Reels get the text-free art prompt, because the renderer adds
    the copy itself; other posts get the finished-graphic prompt with copy.
    """
    from art_generator import build_art_prompt, is_designed

    if content_format.id == "image_reel" or is_designed(record):
        return build_art_prompt(
            {**record, "format_id": content_format.id}, art_style
        )
    return build_ready_design_prompt(
        record, content_format, platform, category_id
    )
