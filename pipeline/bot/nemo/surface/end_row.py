from bot.nemo.surface import on_action
from bot.nemo.views import action, guard, lengths, slowmode

PICKER_ACTION_IDS = (
    f"{guard.END}{lengths.DATE_SUFFIX}",
    f"{guard.END}{lengths.TIME_SUFFIX}",
    f"{slowmode.END}{lengths.DATE_SUFFIX}",
    f"{slowmode.END}{lengths.TIME_SUFFIX}",
    action.UNTIL,
    action.UNTIL_TIME,
)


def ignore_pick(ctx):
    return None


for picker_action_id in PICKER_ACTION_IDS:
    on_action(picker_action_id, open_to_all=True)(ignore_pick)
