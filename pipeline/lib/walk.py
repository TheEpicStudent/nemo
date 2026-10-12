SHORT_AT = 0.9
NO_FLOOR = None

COMPLETE = "complete"
SHORT = "short"
UNVERIFIED = "unverified"


class WalkMismatchError(RuntimeError):
    """The walk did not read the number of items the endpoint reported."""


def check_walk(what, walked_rows, expected, page_size, short_at=SHORT_AT):
    if short_at is not NO_FLOOR and short_at <= 0:
        raise ValueError(
            f"{what}: short_at={short_at} leaves no floor, so no walk can ever read short. "
            "Pass a fraction above 0, or pass walk.NO_FLOOR to say the endpoint has no usable count"
        )

    if expected is None:
        return None

    if walked_rows > expected + page_size:
        raise WalkMismatchError(
            f"{what}: walked {walked_rows} rows against a num_found of {expected}, "
            "refusing to commit"
        )

    if short_at is NO_FLOOR:
        return UNVERIFIED

    floor = int(expected * short_at)
    if expected > 0 and walked_rows < floor:
        print(f"{what}: walked {walked_rows} rows against a num_found of {expected}, under the {floor} floor, short")
        return SHORT

    return COMPLETE


def should_prune(verdict):
    return verdict == COMPLETE


def window_totals(row_counts, window):
    window_rows, other_max_rows = 0, 0
    for start, stop, rows in row_counts:
        if (start, stop) == window:
            window_rows = rows
        else:
            other_max_rows = max(other_max_rows, rows)
    return window_rows, other_max_rows


def supersedes(window_rows, other_max_rows, floor=SHORT_AT):
    return window_rows >= int(other_max_rows * floor)
