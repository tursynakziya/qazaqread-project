"""Compare what the student said with the text and score the reading."""

from difflib import SequenceMatcher

from .models import ReadingSession, WordResult, split_words

# Words at least this similar to the expected word count as read correctly
# (speech recognition often drops or swaps a single letter).
SIMILARITY_THRESHOLD = 0.8


def normalize(word):
    return word.lower().replace("-", "").replace("ё", "е")


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio() >= SIMILARITY_THRESHOLD


def join_hyphenated(expected_words, heard_words):
    """Speech recognition hears "күш-қуат" as two words "күш қуат"; join them back."""
    parts = {}
    for word in expected_words:
        pieces = [p for p in normalize_parts(word) if p]
        if len(pieces) > 1:
            parts.setdefault(len(pieces), {})[tuple(pieces)] = word
    if not parts:
        return heard_words
    result, i = [], 0
    while i < len(heard_words):
        for n in sorted(parts, reverse=True):
            chunk = tuple(normalize(w) for w in heard_words[i : i + n])
            if chunk in parts[n]:
                result.append(parts[n][chunk])
                i += n
                break
        else:
            result.append(heard_words[i])
            i += 1
    return result


def normalize_parts(word):
    return word.lower().replace("ё", "е").split("-")


def align(expected_words, heard_words):
    """
    Return a list of (expected, heard, status) for each expected word the
    student reached. Words after the last word the student read are not
    included: they were not reached, which is not a reading error.
    """
    heard_words = join_hyphenated(expected_words, heard_words)
    exp = [normalize(w) for w in expected_words]
    got = [normalize(w) for w in heard_words]
    results = []
    matcher = SequenceMatcher(None, exp, got, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                results.append((expected_words[i1 + k], heard_words[j1 + k], WordResult.Status.CORRECT))
        elif tag == "replace":
            for k in range(i2 - i1):
                j = j1 + k
                if j < j2:
                    status = WordResult.Status.CORRECT if similar(exp[i1 + k], got[j]) else WordResult.Status.MISREAD
                    results.append((expected_words[i1 + k], heard_words[j], status))
                else:
                    results.append((expected_words[i1 + k], "", WordResult.Status.SKIPPED))
        elif tag == "delete":
            for k in range(i1, i2):
                results.append((expected_words[k], "", WordResult.Status.SKIPPED))
        # "insert": extra words the student said; they do not change the score.

    # Drop the unreached tail.
    while results and results[-1][2] == WordResult.Status.SKIPPED:
        results.pop()
    return results


def analyze_session(session: ReadingSession):
    """Fill word results and scores for a session from its transcript."""
    expected = split_words(session.text.body)
    heard = split_words(session.transcript)
    session.word_results.all().delete()

    if heard:
        rows = align(expected, heard)
        session.status = ReadingSession.Status.COMPLETED
    else:
        # Nothing recognised: keep every word for the teacher to mark by ear.
        rows = [(w, "", WordResult.Status.MISREAD) for w in expected]
        session.status = ReadingSession.Status.NEEDS_REVIEW

    WordResult.objects.bulk_create(
        WordResult(session=session, position=i, expected=e[:100], heard=h[:100], status=s)
        for i, (e, h, s) in enumerate(rows)
    )
    session.recalculate()
    return session
