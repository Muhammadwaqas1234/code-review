"""Robust JSON extraction from LLM output."""

import pytest

from app.utils.json_utils import extract_json


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ("```\n{\"a\": 1}\n```", {"a": 1}),
        ("Sure! Here:\n```json\n{\"a\": [1, 2]}\n```\nHope that helps!", {"a": [1, 2]}),
        ('The answer is {"nested": {"b": "has } brace in string"}} ok',
         {"nested": {"b": "has } brace in string"}}),
        ('[1, 2, 3] trailing words', [1, 2, 3]),
        ('broken {"a": } then valid {"b": 2}', {"b": 2}),
        ('prefix {"a": "quote \\" and brace }"} suffix', {"a": 'quote " and brace }'}),
        ("no json here at all", None),
        ("", None),
        (None, None),
        ("   ", None),
        ("42", None),  # bare scalar is not an object/array
        ('"just a string"', None),
    ],
)
def test_extract_json(text, expected):
    assert extract_json(text) == expected


def test_extract_json_deeply_nested():
    text = 'noise {"a": {"b": {"c": [1, {"d": 2}]}}} noise'
    assert extract_json(text) == {"a": {"b": {"c": [1, {"d": 2}]}}}
