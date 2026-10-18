def notice(text, body):
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if body:
        blocks.append({"type": "rich_text", "elements": [{
            "type": "rich_text_preformatted", "elements": [{"type": "text", "text": body}],
        }]})
    return {"text": text, "blocks": blocks}
