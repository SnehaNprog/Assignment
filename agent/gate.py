"""Cheap first look at a member's message: is it worth a model call?

The small classifier (classifier/predict.py) decides, backed by a keyword net,
because missing a real request is worse than a wasted call. Cancellations
never pass through here (concierge.py always sends them to the model).
"""
from __future__ import annotations

import re

_HINT = re.compile(
    r"\?|\b(?:book|table|reserv\w*|arrange|organi[sz]e|need|want|get (?:us|me)|can you|could you|pls|please|"
    r"kindly|kar do|karwa|chahiye|send|find|change|move|push|update|confirm|cancel|tickets?|car|cab|flight|"
    r"hotel|dinner|lunch|brunch)\b", re.I)

_predict = None


def _classifier():
    global _predict
    if _predict is None:
        try:
            from classifier.predict import predict
            _predict = predict
        except Exception:  # no trained model on this machine: keywords only
            _predict = False
    return _predict


def is_request(text: str) -> bool:
    if _HINT.search(text):
        return True
    predict = _classifier()
    return bool(predict) and predict([text])[0] == "request"
