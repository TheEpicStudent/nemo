def header(case_id, url=None):
    return f"<{url}|Case {case_id}>" if url else f"Case {case_id}"


def people(user_ids, actor=None):
    named = ["themselves" if one == actor else f"<@{one}>" for one in user_ids]
    if len(named) < 2:
        return "".join(named)
    return ", ".join(named[:-1]) + f" and {named[-1]}"


def claimed(actor, case_id):
    return f"<@{actor}> claimed case {case_id}"


def assigned(actor, case_id, user_ids):
    others = [one for one in user_ids if one != actor]
    lines = [claimed(actor, case_id)] if actor in user_ids else []
    if others:
        lines.append(f"<@{actor}> assigned case {case_id} to {people(others)}")
    return lines


def unassigned(actor, case_id, user_ids):
    return f"<@{actor}> unassigned {people(user_ids, actor)} from case {case_id}"


def number(case_id, url=None):
    return f"<{url}|{case_id}>" if url else str(case_id)


def merged(actor, duplicate_ids, target_id, url_of=lambda case_id: None):
    numbers = [number(one, url_of(one)) for one in duplicate_ids]
    if len(numbers) == 1:
        listed = f"case {numbers[0]}"
    else:
        listed = "cases " + ", ".join(numbers[:-1]) + f" and {numbers[-1]}"
    return f"<@{actor}> merged {listed} into case {number(target_id, url_of(target_id))}"


def resolved(actor, case_id, label=None):
    line = f"<@{actor}> resolved case {case_id}"
    return f"{line} · {label}" if label else line


def reopened(actor, case_id):
    return f"<@{actor}> reopened case {case_id}"


def reopened_by_reporter(case_id, was_label):
    return f"Case {case_id} reopened by a reporter reply (was: {was_label})"


def note_added(actor, body):
    return f"<@{actor}> added a note: {body}"


def already_claimed(case_id):
    return f"You are already assigned to case {case_id}"


def already_assigned(case_id, user_ids):
    verb = "is" if len(user_ids) == 1 else "are"
    return f"{people(user_ids)} {verb} already assigned to case {case_id}"


def not_assigned(case_id, user_ids):
    verb = "is" if len(user_ids) == 1 else "are"
    return f"{people(user_ids)} {verb} not assigned to case {case_id}"


def already_resolved(case_id):
    return f"Case {case_id} is already resolved and has no open report"


def not_permitted(reason):
    return f"Not permitted: {reason}"


ASSIGN_USAGE = "Usage: `!assign @user`"
UNASSIGN_USAGE = "Usage: `!unassign @user`"
NOTE_USAGE = "Usage: `!note <text>` or `!note @user <text>`"
