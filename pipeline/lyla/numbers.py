POOL_SIZE = 3

POOLED = "SELECT count(*) FROM fd.lyla_case_numbers"

RESERVE = "SELECT nextval('cases_case_number_seq') FROM generate_series(1, %s)"

KEEP = "INSERT INTO fd.lyla_case_numbers (number) VALUES (%s) ON CONFLICT DO NOTHING"


def refill(conn, lyla, size=POOL_SIZE):
    missing = size - conn.execute(POOLED).fetchone()[0]
    if missing <= 0:
        return []
    numbers = [row[0] for row in lyla.execute(RESERVE, (missing,)).fetchall()]
    lyla.commit()
    for number in numbers:
        conn.execute(KEEP, (number,))
    conn.commit()
    return numbers
