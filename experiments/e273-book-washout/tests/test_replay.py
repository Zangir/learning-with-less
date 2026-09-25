"""Focused semantic checks; no network or raw source data required."""
from collections import Counter
from replay import Book


def event(oid, diff):
    return dict(oid=oid, user='synthetic', coin='BTC', side='B', px='90000.0', raw_book_diff=diff)


book, counts = Book(), Counter()
seq = [event(1, {'new': {'sz':'2.0'}}),
       event(1, {'update': {'origSz':'2.00', 'newSz':'1.0'}}),
       event(1, 'remove'), event(2, 'remove'),
       event(3, {'update': {'origSz':'3.0', 'newSz':'2.0'}}),
       event(2, 'remove'), event(1, {'update': {'origSz':'1', 'newSz':'0.5'}}),
       event(1, {'new': {'sz':'9'}}), event(3, {'new': {'sz':'9'}}),
       event(3, {'update': {'origSz':'7', 'newSz':'1'}})]
for line, rec in enumerate(seq, 1):
    book.apply(rec, 0, line, counts)
assert counts['legacy_update'] == 1 and counts['legacy_remove'] == 1
assert len(book.seen) == 3 and list(book.live) == [3]
assert book.live[3][0] == '1'
assert counts['anomaly_events'] == 5
assert counts['origSz_mismatch'] == 1
assert counts['btc_events'] == sum(counts[k+'_events'] for k in ('new','update','remove'))
assert book.seen.deserialize(book.seen.serialize()) == book.seen
print('PASS: first-seen classification, persistent seen set, decimal size comparison, five anomaly paths, serialization')
