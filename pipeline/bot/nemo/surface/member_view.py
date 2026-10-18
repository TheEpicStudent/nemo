from bot.core import session
from bot.nemo import case_actions
from bot.nemo.surface import on_action, on_view
from bot.nemo.views import case_menu, member_view

NO_NOTE = "Enter the note"


def action_user_id(ctx):
    for one in ctx.body.get("actions") or []:
        value = str(one.get("value") or "")
        if value:
            return value
    return None


@on_action(member_view.ADD_NOTE, needs="member.note")
def open_member_note(ctx):
    user_id = action_user_id(ctx)
    if user_id is None:
        return None
    return ctx.client.views_push(trigger_id=ctx.trigger_id, view=member_view.note_view(user_id))


@on_view(member_view.NOTE_CALLBACK, needs="member.note", refuse_block=member_view.NOTE_TEXT)
def submit_member_note(ctx):
    user_id = ctx.view.get("private_metadata") or ""
    text = case_menu.typed(ctx.view.get("state") or {}, member_view.NOTE_TEXT)
    if not text:
        return ctx.ack(response_action="errors", errors={member_view.NOTE_TEXT: NO_NOTE})
    with session() as conn:
        case_actions.member_note(conn, user_id, text, ctx.user_id)
    ctx.ack(response_action="clear")
    return user_id
