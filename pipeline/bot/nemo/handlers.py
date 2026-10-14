import logging
import re

from bot.core import access, session
from bot.nemo import answer, views, chat, memberguards, surface, thread_commands
from bot.nemo.case_actions import (
    CASE_CATEGORY,
    CASE_ASSIGNEES,
    OPEN_REPORTS,
    STILL_OPEN,
    add_participants,
    assign_people,
    claimed,
    counted,
    mark_resolution_echo_pending,
    add_note,
    live_actions,
    log_action,
    merge,
    mergeable,
    participants,
    remove_assignee,
    remove_participant,
    reopen,
    resolve_and_tell,
    resolution_echo_actions,
    resolve,
    reverse_action,
    set_category,
)
from bot.nemo.surface.reaction_watch import after_resolve
from bot.nemo.channel import (
    ASSIGNEES,
    SUBJECTS,
    case_channels,
    post_action_echo,
    post_ephemeral,
    post_line,
    post_merge_note,
    post_resolution_echo,
    refresh_card,
)

log = logging.getLogger("bot.nemo")

RESOLVED_MARK = "check-check"


def register(app, on_reply=None):
    def claim(case_id, user_id):
        with session() as conn:
            allowed, refusal = access.may(conn, user_id, "case.open")
            if not allowed:
                return refusal
            if not conn.execute(STILL_OPEN, (case_id,)).fetchone()[0]:
                return f"Case {case_id} is already resolved."
            assignees = [row[0] for row in conn.execute(CASE_ASSIGNEES, (case_id,)).fetchall()]
            if user_id in assignees:
                return views.lines.already_claimed(case_id)
            claimed(conn, case_id, user_id)

        log.info("nemo: case %s claimed by %s", case_id, user_id)
        return None

    def people_view(conn, case_id, user_id):
        can_people, refusal = access.may(conn, user_id, "case.people", case_id)
        can_assign, _ = access.may(conn, user_id, "case.open", case_id)
        if not (can_people or can_assign):
            return None, refusal
        still_open = conn.execute(STILL_OPEN, (case_id,)).fetchone()[0]
        assignees = [row[0] for row in conn.execute(ASSIGNEES, (case_id,)).fetchall()]
        return views.people.build_view(
            case_id, participants(conn, case_id), assignees,
            can_people=can_people, can_assign=bool(can_assign and still_open),
        ), None

    def more_view(conn, case_id, problem=None):
        still_open = conn.execute(STILL_OPEN, (case_id,)).fetchone()[0]
        category_row = conn.execute(CASE_CATEGORY, (case_id,)).fetchone()
        options = views.edit.more_options(
            still_open, category_row[0] if category_row else None, live_actions(conn, case_id)
        )
        return views.edit.more_view(case_id, options, problem)

    NEEDS = {
        views.edit.LOG_ACTION: "case.act",
        views.edit.RESOLVE: "case.resolve",
        views.edit.REOPEN: "case.reopen",
        views.edit.REVERSE: "case.reverse",
        views.edit.MERGE: "case.resolve",
        views.edit.CATEGORY: "case.categorise",
        views.edit.NOTE: "case.note",
    }

    def view_for(verb, case_id, user_id):
        with session() as conn:
            if verb in (views.edit.PEOPLE, views.edit.ASSIGNEES):
                return people_view(conn, case_id, user_id)
            if verb == views.edit.MORE:
                return more_view(conn, case_id), None
            needed = NEEDS.get(verb)
            if needed is None:
                return None, None
            allowed, refusal = access.may(conn, user_id, needed, case_id)
            if not allowed:
                return None, refusal

            if verb == views.edit.LOG_ACTION:
                subjects = [row[0] for row in conn.execute(SUBJECTS, (case_id,)).fetchall()]
                category_row = conn.execute(CASE_CATEGORY, (case_id,)).fetchone()
                return views.action.build_view(case_id, subjects, category_row[0] if category_row else None), None
            if verb == views.edit.RESOLVE:
                live = live_actions(conn, case_id)
                open_ones = counted(conn, OPEN_REPORTS, case_id)
                return views.resolve.build_view(case_id, live, open_ones), None
            if verb == views.edit.REVERSE:
                live = live_actions(conn, case_id)
                if not live:
                    return None, f"No active actions to reverse on *case {case_id}*."
                return views.reverse.build_view(case_id, live), None
            if verb == views.edit.MERGE:
                return views.merge.build_view(mergeable(conn, [case_id]), target=case_id), None
            if verb == views.edit.REOPEN:
                return views.edit.reopen_view(case_id), None
            if verb == views.edit.CATEGORY:
                return views.edit.category_view(case_id), None
            return views.edit.note_view(case_id), None

    def refuse(client, body, case_id, text):
        if body.get("message"):
            return post_ephemeral(client, body, text)
        current_view = body.get("view") or {}
        if not current_view.get("id"):
            return None
        with session() as conn:
            view = more_view(conn, case_id, text)
        try:
            client.views_update(view_id=current_view["id"], hash=current_view.get("hash"), view=view)
        except Exception as failure:
            log.warning("nemo: could not say why case %s was refused: %s", case_id, failure)
        return None

    def act(verb, case_id, body, client):
        user_id = body["user"]["id"]
        if verb == views.edit.CLAIM:
            problem = claim(case_id, user_id)
            return refuse(client, body, case_id, problem) if problem else None

        view, refusal = view_for(verb, case_id, user_id)
        if refusal:
            return refuse(client, body, case_id, refusal)
        if view is None:
            return None
        if body.get("view"):
            return client.views_push(trigger_id=body["trigger_id"], view=view)
        return client.views_open(trigger_id=body["trigger_id"], view=view)

    @app.action(views.edit.MENU)
    def on_menu(ack, body, client):
        ack()
        verb, case_id = views.edit.parse_menu_value(body["actions"][0]["selected_option"]["value"])
        if case_id is not None:
            act(verb, case_id, body, client)

    @app.action(re.compile(f"^{views.edit.MORE_ACTION}_"))
    def on_more_action(ack, body, client):
        ack()
        verb, case_id = views.edit.parse_menu_value(body["actions"][0]["value"])
        if case_id is not None:
            act(verb, case_id, body, client)

    @app.action(views.edit.BAN_LOG)
    def on_ban_log(ack, body, client):
        ack()
        case_id, target = views.edit.parse_ban_value(body["actions"][0]["value"])
        if case_id is None:
            return None
        user_id = body["user"]["id"]
        with session() as conn:
            allowed, refusal = access.may(conn, user_id, "case.act", case_id)
            if not allowed:
                return post_ephemeral(client, body, refusal)
            subjects = [row[0] for row in conn.execute(SUBJECTS, (case_id,)).fetchall()]
            category_row = conn.execute(CASE_CATEGORY, (case_id,)).fetchone()
        if target:
            subjects = [target, *[one for one in subjects if one != target]]
        return client.views_open(
            trigger_id=body["trigger_id"],
            view=views.action.build_view(case_id, subjects, category_row[0] if category_row else None),
        )

    @app.action(views.edit.CLAIM)
    def on_claim(ack, body, client):
        ack()
        act(views.edit.CLAIM, int(body["actions"][0]["value"]), body, client)

    @app.action(views.edit.LOG_ACTION)
    def on_log_action(ack, body, client):
        ack()
        act(views.edit.LOG_ACTION, int(body["actions"][0]["value"]), body, client)

    @app.action(views.edit.RESOLVE)
    def on_resolve_action(ack, body, client):
        ack()
        act(views.edit.RESOLVE, int(body["actions"][0]["value"]), body, client)

    def settle(conn, case_id, values):
        return memberguards.settle(
            conn,
            values.get("type_key"),
            values.get("target_user_id"),
            case_id,
            values.get("channel_id"),
        )

    def reshape(ack, body, client):
        ack()
        submitted_view = body.get("view") or {}
        if submitted_view.get("callback_id") != views.action.CALLBACK:
            return

        case_id = int(submitted_view["private_metadata"])
        values = views.action.submitted_values(submitted_view["state"])
        with session() as conn:
            guard_status = settle(conn, case_id, values)

        try:
            client.views_update(
                view_id=submitted_view["id"],
                hash=submitted_view["hash"],
                view=views.action.build_view(case_id, values=values, guard_status=guard_status),
            )
        except Exception as failure:
            log.warning("nemo: could not reshape the action modal: %s", failure)

    for where in (views.action.KIND, views.action.TARGET, views.action.WHERE):
        app.action(where)(reshape)

    @app.view(views.action.CALLBACK)
    def on_action_logged(ack, body, view, client):
        case_id = int(view["private_metadata"])
        user_id = body["user"]["id"]
        values = views.action.submitted_values(view["state"])

        with session() as conn:
            guard_status = settle(conn, case_id, values)

        block_ids = {block.get("block_id") for block in view.get("blocks", [])}
        if views.action.requires_refresh(values, block_ids, guard_status):
            return ack(
                response_action="update",
                view=views.action.build_view(case_id, values=values, guard_status=guard_status),
            )

        errors = views.action.validation_errors(values)
        if errors:
            return ack(response_action="errors", errors=errors)

        with session() as conn:
            allowed, refusal = access.may(conn, user_id, "case.act", case_id)
            if not allowed:
                return ack(
                    response_action="errors",
                    errors={views.action.KIND: refusal},
                )
            current_guard_status = settle(conn, case_id, values)
            action_id = log_action(conn, case_id, values, user_id)
            guard_id = memberguards.settled(conn, action_id, values, current_guard_status, user_id)

        ack()
        with session() as conn:
            refresh_card(client, conn, case_id)
            post_action_echo(client, conn, case_id, values, user_id)
        log.info("nemo: action %s logged on case %s by %s, guard %s",
                 action_id, case_id, user_id, guard_id)

    @app.view(views.reverse.CALLBACK)
    def on_reversed(ack, body, view, client):
        case_id = int(view["private_metadata"])
        user_id = body["user"]["id"]
        values = views.reverse.submitted_values(view["state"])

        errors = views.reverse.validation_errors(values)
        if errors:
            return ack(response_action="errors", errors=errors)

        with session() as conn:
            allowed, refusal = access.may(conn, user_id, "case.reverse", case_id)
            if not allowed:
                return ack(response_action="errors", errors={views.reverse.WHICH: refusal})
            done = reverse_action(conn, case_id, values["action_id"], values["reason"], user_id)

        if not done:
            return ack(
                response_action="errors",
                errors={views.reverse.WHICH: "That action is no longer active on this case."},
            )

        ack()
        with session() as conn:
            refresh_card(client, conn, case_id)
        log.info("nemo: action %s reversed on case %s by %s", values["action_id"], case_id, user_id)

    @app.action(views.people.REMOVE)
    def on_person_removed(ack, body, client):
        ack()
        user_id, role, case_id = views.people.removed(body["actions"][0]["value"])
        actor = body["user"]["id"]
        if case_id is None:
            return None

        needed = "case.open" if role == views.people.ASSIGNEE else "case.people"
        with session() as conn:
            allowed, refusal = access.may(conn, actor, needed, case_id)
            if not allowed:
                log.info("nemo: %s may not take %s off case %s: %s", actor, user_id, case_id, refusal)
                return None
            if role == views.people.ASSIGNEE:
                remove_assignee(conn, case_id, user_id, actor)
            else:
                remove_participant(conn, case_id, user_id, role, actor)
            updated_view, _ = people_view(conn, case_id, actor)

        if updated_view:
            try:
                client.views_update(
                    view_id=body["view"]["id"], hash=body["view"]["hash"], view=updated_view
                )
            except Exception as failure:
                log.warning("nemo: could not refresh the people modal: %s", failure)

        with session() as conn:
            refresh_card(client, conn, case_id)
        log.info("nemo: %s taken off case %s (%s) by %s", user_id, case_id, role, actor)
        return None

    @app.view(views.people.CALLBACK)
    def on_people_submitted(ack, body, view, client):
        case_id = int(view["private_metadata"])
        user_id = body["user"]["id"]
        values = views.people.submitted_values(view["state"])
        block_ids = {block.get("block_id") for block in view.get("blocks", [])}

        errors = views.people.validation_errors(values, block_ids)
        if errors:
            return ack(response_action="errors", errors=errors)

        with session() as conn:
            if values["subjects"]:
                allowed, refusal = access.may(conn, user_id, "case.people", case_id)
                if not allowed:
                    return ack(response_action="errors", errors={views.people.WHO: refusal})
            if values["assignees"]:
                allowed, refusal = access.may(conn, user_id, "case.open", case_id)
                if not allowed:
                    return ack(response_action="errors", errors={views.people.ASSIGN: refusal})
                if not conn.execute(STILL_OPEN, (case_id,)).fetchone()[0]:
                    return ack(
                        response_action="errors",
                        errors={views.people.ASSIGN: f"Case {case_id} is already resolved."},
                    )
            added = add_participants(
                conn, case_id, values["subjects"], views.people.SUBJECT, user_id
            ) if values["subjects"] else []
            assigned = assign_people(
                conn, case_id, values["assignees"], user_id
            ) if values["assignees"] else []
            updated_view, _ = people_view(conn, case_id, user_id)

        ack(response_action="update", view=updated_view)
        with session() as conn:
            refresh_card(client, conn, case_id)
        log.info("nemo: case %s gained subjects %s and assignees %s from %s",
                 case_id, added, assigned, user_id)
        return None

    @app.view(views.edit.CATEGORY)
    def on_category(ack, body, view, client):
        case_id = int(view["private_metadata"])
        user_id = body["user"]["id"]
        key = views.edit.selected_category(view["state"])

        with session() as conn:
            allowed, refusal = access.may(conn, user_id, "case.categorise", case_id)
            if not allowed:
                return ack(response_action="errors", errors={views.edit.WHAT: refusal})
            updated = set_category(conn, case_id, key, user_id)

        if not updated:
            return ack(
                response_action="errors",
                errors={views.edit.WHAT: f"Case {case_id} already has a violation."},
            )

        ack()
        with session() as conn:
            refresh_card(client, conn, case_id)
        log.info("nemo: case %s is %s", case_id, key)
        return None

    @app.view(views.edit.NOTE)
    def on_note(ack, body, view, client):
        case_id = int(view["private_metadata"])
        user_id = body["user"]["id"]
        values = views.edit.submitted_values(view["state"])

        errors = views.edit.note_objection(values)
        if errors:
            return ack(response_action="errors", errors=errors)

        with session() as conn:
            allowed, refusal = access.may(conn, user_id, "case.note", case_id)
            if not allowed:
                return ack(response_action="errors", errors={views.edit.NOTE_BODY: refusal})
            note_id = add_note(conn, case_id, values, user_id)

        ack()
        log.info("nemo: note %s kept on case %s", note_id, case_id)
        return None

    @app.action(views.report.OPEN)
    def on_open(ack):
        ack()

    def reopen_now(client, case_id, user_id):
        with session() as conn:
            allowed, refusal = access.may(conn, user_id, "case.reopen", case_id)
            if not allowed:
                return refusal
            reopened = reopen(conn, case_id, user_id)

        if not reopened:
            return f"Case {case_id} is already open."

        with session() as conn:
            refresh_card(client, conn, case_id)
            post_line(client, conn, case_id, views.lines.reopened(user_id, case_id))
        log.info("nemo: case %s reopened by %s", case_id, user_id)
        return None

    @app.action(views.edit.REOPEN)
    def on_reopen(ack, body, client):
        ack()
        case_id = int(body["actions"][0]["value"])
        problem = reopen_now(client, case_id, body["user"]["id"])
        if problem:
            post_ephemeral(client, body, problem)

    @app.view(views.edit.REOPEN_CONFIRMED)
    def on_reopen_confirmed(ack, body, view, client):
        case_id = int(view["private_metadata"])
        problem = reopen_now(client, case_id, body["user"]["id"])
        if problem:
            return ack(response_action="update", view=views.edit.notice_view(case_id, problem))
        return ack()

    @app.view(views.merge.CALLBACK)
    def on_merged(ack, body, view, client):
        user_id = body["user"]["id"]
        values = views.merge.submitted_values(view["state"])

        errors = views.merge.validation_errors(values)
        if errors:
            return ack(response_action="errors", errors=errors)

        with session() as conn:
            for case_id in (values["target"], *values["duplicates"]):
                allowed, refusal = access.may(conn, user_id, "case.resolve", case_id)
                if not allowed:
                    return ack(response_action="errors", errors={views.merge.DUPLICATES: refusal})
            closed = merge(conn, values["target"], values["duplicates"], user_id)

        if not closed:
            return ack(
                response_action="errors",
                errors={views.merge.DUPLICATES: "Those cases are already resolved."},
            )

        ack(response_action="clear")
        with session() as conn:
            for case_id in closed:
                refresh_card(client, conn, case_id)
            post_merge_note(client, conn, values["target"], closed, user_id)
        log.info("nemo: cases %s merged into %s by %s", closed, values["target"], user_id)
        return None

    @app.view(views.resolve.CALLBACK)
    def on_resolved(ack, body, view, client):
        case_id = int(view["private_metadata"])
        user_id = body["user"]["id"]

        with session() as conn:
            live = live_actions(conn, case_id)
        values = views.resolve.submitted_values(view["state"], live)

        errors = views.resolve.validation_errors(values)
        if errors:
            return ack(response_action="errors", errors=errors)

        with session() as conn:
            allowed, refusal = access.may(conn, user_id, "case.resolve", case_id)
            if not allowed:
                return ack(response_action="errors", errors={views.resolve.WHY: refusal})
            notified = resolve(conn, case_id, values, user_id)
            if notified:
                mark_resolution_echo_pending(conn, case_id, user_id)

        if notified is None:
            return ack(
                response_action="errors",
                errors={views.resolve.WHY: f"Case {case_id} was already resolved."},
            )

        ack()
        with session() as conn:
            refresh_card(client, conn, case_id)
            if not notified:
                actions = resolution_echo_actions(conn, case_id)
                post_resolution_echo(client, conn, case_id, values["resolution"],
                    values["member_note"], user_id, actions)
        log.info("nemo: case %s resolved by %s, %s notified", case_id, user_id, notified)

    def post_refusal(event, thread_ts, client, refusal):
        try:
            client.reactions_add(
                channel=event["channel"], timestamp=event["ts"], name=answer.STUCK
            )
            client.chat_postEphemeral(
                channel=event["channel"],
                user=event["user"],
                thread_ts=thread_ts,
                text=refusal,
            )
        except Exception as failure:
            log.warning("nemo: could not say why it was refused: %s", failure)

    def may_answer(event, thread_ts, client):
        with session() as conn:
            case_id = chat.case_of_thread(conn, thread_ts)
            allowed, refusal = access.may(conn, event.get("user"), "case.reply", case_id)
        if allowed:
            return True

        post_refusal(event, thread_ts, client, refusal)
        log.info("nemo: refused an answer from %s on case %s", event.get("user"), case_id)
        return False

    def on_message(event, client):
        if event.get("channel") not in case_channels():
            return

        subtype = event.get("subtype")
        if subtype == "message_changed":
            return on_changed(event)
        if subtype == "message_deleted":
            return on_deleted(event)
        if event.get("bot_id") or subtype not in (None, "file_share"):
            return

        thread_ts = event.get("thread_ts")
        if not thread_ts or thread_ts == event.get("ts"):
            return

        verb, args = thread_commands.parse_command(event.get("text"))
        if verb == thread_commands.RESOLVE:
            return resolve_from_thread(event, thread_ts, client)
        if verb:
            return thread_commands.handle(client, event, thread_ts, verb, args)

        parsed_answer = answer.read(event.get("text"))
        if parsed_answer and for_the_member(thread_ts):
            return reply(event, thread_ts, parsed_answer, client)

        return record_chat(event, thread_ts, client)

    def resolve_from_thread(event, thread_ts, client):
        user_id = event.get("user")
        with session() as conn:
            case_id = chat.case_of_thread(conn, thread_ts)
            if case_id is None:
                return None
            for needed in ("case.reply", "case.resolve"):
                allowed, refusal = access.may(conn, user_id, needed, case_id)
                if not allowed:
                    break

        if not allowed:
            thread_commands.reply(client, event, thread_ts,
                                  thread_commands.refused(refusal))
            return None

        with session() as conn:
            resolution, notified = resolve_and_tell(
                conn, case_id, views.resolve.default_message(), user_id
            )
            if resolution and notified:
                mark_resolution_echo_pending(conn, case_id, user_id)

        if resolution is None and not notified:
            thread_commands.reply(client, event, thread_ts,
                                  thread_commands.refused(views.lines.already_resolved(case_id)))
            return None

        try:
            client.reactions_add(channel=event["channel"], timestamp=event["ts"],
                                 name=RESOLVED_MARK)
        except Exception as failure:
            log.warning("nemo: could not mark %s as done: %s", event["ts"], failure)
        if resolution:
            after_resolve(client, case_id, resolution, user_id, echo=not notified)
        log.info("nemo: case %s resolved from the thread by %s, %s told", case_id, user_id, notified)
        return case_id

    def for_the_member(thread_ts):
        with session() as conn:
            return chat.reaches_a_member(conn, thread_ts)

    def reply(event, thread_ts, parsed_answer, client):
        if on_reply is None:
            return None
        if not may_answer(event, thread_ts, client):
            return None

        return on_reply(
            thread_ts,
            parsed_answer["body"],
            event.get("user"),
            signed=parsed_answer["signed"],
            files=event.get("files") or [],
            at=(event["channel"], event["ts"]),
        )

    def record_chat(event, thread_ts, client):
        with session() as conn:
            case_id = chat.case_of_thread(conn, thread_ts)
            if case_id is None:
                return
            allowed, refusal = access.may(conn, event.get("user"), "case.chat", case_id)

        if not allowed:
            post_refusal(event, thread_ts, client, refusal)
            log.info("nemo: refused chat from %s on case %s", event.get("user"), case_id)
            return

        with session() as conn:
            chat_id, inserted = chat.store_message(conn, case_id, event)

        if inserted:
            log.info("nemo: case %s heard us say something (%s)", case_id, chat_id)

    def on_changed(event):
        message = event.get("message") or {}
        if not message.get("ts") or message.get("subtype") == "bot_message":
            return
        with session() as conn:
            changed = chat.edit(conn, event["channel"], message)
        if changed:
            log.info("nemo: chat %s was edited", changed)

    def on_deleted(event):
        if not event.get("deleted_ts"):
            return
        with session() as conn:
            deleted_id = chat.delete(conn, event["channel"], event["deleted_ts"])
        if deleted_id:
            log.info("nemo: chat %s was deleted in slack, the words are kept", deleted_id)

    surface.bind(
        surface.EVENT, "message",
        lambda ctx: on_message(ctx.payload, ctx.client),
        tag="handlers.on_message",
    )
