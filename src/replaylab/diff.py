"""Align sequential runs by position, comparing semantic data rather than timings."""

from replaylab.store import Store


def compare(store: Store, left_id: str, right_id: str) -> dict:
    left, right = store.steps(left_id), store.steps(right_id)
    fields = ("kind", "name", "request", "output", "error", "state_before", "state_after")
    rows = []
    for index in range(max(len(left), len(right))):
        a = left[index] if index < len(left) else None
        b = right[index] if index < len(right) else None
        changed_fields = [f for f in fields if a is None or b is None or a[f] != b[f]]
        status = ("added" if a is None else "removed" if b is None
                  else "changed" if changed_fields else "unchanged")
        rows.append(dict(position=index + 1, status=status, fields=changed_fields, left=a, right=b))
    return dict(left=store.get_run(left_id), right=store.get_run(right_id), steps=rows,
                changed=sum(row["status"] != "unchanged" for row in rows))
