"""Minimal, dependency-free replacement for the (unpublished) ``sortedlist`` package.

The reference comparator (``comparator.py``) imports ``from sortedlist import
SortedList``. That package is not published on PyPI, and ``sortedcontainers`` has a
different API (``.add`` / ``.remove`` that raises) which is not a drop-in: the
comparator relies on ``SortedList.remove(x)`` returning a boolean (True if an equal
element was removed, False otherwise).

The comparison algorithm only ever uses equality (``remove`` and ``==``); it never
orders elements. So a list-backed multiset with the same four operations is
behaviorally identical. Elements are matched by ``==`` (not hashing), so this also
works for values that are equal-comparable but not hashable.
"""


class SortedList:
    def __init__(self, iterable=None):
        self._data = list(iterable) if iterable is not None else []

    def insert(self, value):
        self._data.append(value)

    def add(self, value):
        # Aliased for API familiarity; behaves like insert().
        self._data.append(value)

    def remove(self, value):
        try:
            self._data.remove(value)
            return True
        except ValueError:
            return False

    def __contains__(self, value):
        return value in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)
