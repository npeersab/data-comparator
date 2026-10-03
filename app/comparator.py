#  Copyright (c) 2019. Noorulhasan Peersab <npeersab77@gmail.com>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
#  Derived from https://github.com/npeersab/Universal-Data-Comparator
#  (comparator.py). The original was reused in spirit (same streaming design,
#  same two-buffer "cancel unmatched records" approach, same function signature
#  and SortedList usage) but its control flow was BUGGY and produced wrong
#  results, so it has been corrected here.
#
#  Bugs fixed vs. the original:
#    1. Sentinel leak: it initialised source_record/target_record = None and,
#       when a stream was empty, could insert that None sentinel into the
#       mismatch output (compare([], []) returned ([], [None])).
#    2. Undercounting: in the stream-exhaustion / cancellation branches it could
#       drop a genuine mismatch, so source-only / target-only counts were wrong.
#
#  This version correctly computes the multiset difference (order-independent):
#  records present in source but not target, and vice versa, with multiplicity.
#  It stops early once either mismatch buffer reaches max_mismatch_size.

from .sortedlist import SortedList

_SENTINEL = object()


def _advance(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return _SENTINEL


def _match_and_remove(buf, value):
    """Remove one element equal to `value` from `buf`; return True if removed."""
    if value in buf:
        buf.remove(value)
        return True
    return False


def compare(source_records: iter, target_records: iter, *, max_mismatch_size):
    source_mismatch = SortedList()
    target_mismatch = SortedList()

    src_iter = iter(source_records)
    tgt_iter = iter(target_records)
    s = _advance(src_iter)
    t = _advance(tgt_iter)

    def exceeded():
        return (
            len(source_mismatch) >= max_mismatch_size
            or len(target_mismatch) >= max_mismatch_size
        )

    while True:
        if s is _SENTINEL and t is _SENTINEL:
            break

        if s is not _SENTINEL and t is not _SENTINEL:
            if s == t:
                s = _advance(src_iter)
                t = _advance(tgt_iter)
            elif _match_and_remove(target_mismatch, s):
                # s matches a target record that was pending a source match.
                s = _advance(src_iter)
            elif _match_and_remove(source_mismatch, t):
                # t matches a source record that was pending a target match.
                t = _advance(tgt_iter)
            else:
                source_mismatch.insert(s)
                target_mismatch.insert(t)
                s = _advance(src_iter)
                t = _advance(tgt_iter)
            if exceeded():
                return source_mismatch, target_mismatch
            continue

        # Exactly one side is exhausted; drain the other.
        if s is _SENTINEL:
            # Remaining target records are target-only unless they match a
            # source record still pending in source_mismatch.
            if t is not _SENTINEL and not _match_and_remove(source_mismatch, t):
                target_mismatch.insert(t)
            for x in tgt_iter:
                if not _match_and_remove(source_mismatch, x):
                    target_mismatch.insert(x)
        else:
            if s is not _SENTINEL and not _match_and_remove(target_mismatch, s):
                source_mismatch.insert(s)
            for x in src_iter:
                if not _match_and_remove(target_mismatch, x):
                    source_mismatch.insert(x)
        break

    return source_mismatch, target_mismatch
