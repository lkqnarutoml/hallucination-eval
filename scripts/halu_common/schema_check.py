"""A small JSON Schema validator (standard library only).

Supports the subset used by assets/findings.schema.json: type (single or list), enum, const,
properties, required, additionalProperties (false), items, minItems, maxItems, minimum, maximum,
minLength, maxLength, pattern, anyOf, oneOf, allOf, and local $ref into "#/$defs/...".
validate() returns a list of human-readable error strings with JSON-pointer style paths.
"""
from __future__ import annotations

import re
from typing import Any, List

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


def _resolve_ref(root: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise ValueError("only local refs are supported: %s" % ref)
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def validate(instance: Any, schema: dict, root: dict = None, path: str = "$") -> List[str]:
    root = root if root is not None else schema
    errors: List[str] = []
    if "$ref" in schema:
        schema = dict(_resolve_ref(root, schema["$ref"]), **{k: v for k, v in schema.items() if k != "$ref"})
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_TYPE_CHECKS.get(t, lambda v: True)(instance) for t in types):
            errors.append("%s: expected type %s, got %s" % (path, "/".join(types), type(instance).__name__))
            return errors
    if "enum" in schema and instance not in schema["enum"]:
        errors.append("%s: value %r not in enum %r" % (path, instance, schema["enum"]))
    if "const" in schema and instance != schema["const"]:
        errors.append("%s: value %r != const %r" % (path, instance, schema["const"]))
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append("%s: string shorter than %d" % (path, schema["minLength"]))
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append("%s: string longer than %d" % (path, schema["maxLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append("%s: %r does not match pattern %s" % (path, instance, schema["pattern"]))
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append("%s: %r below minimum %r" % (path, instance, schema["minimum"]))
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append("%s: %r above maximum %r" % (path, instance, schema["maximum"]))
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append("%s: missing required property %r" % (path, key))
        for key, sub in props.items():
            if key in instance:
                errors.extend(validate(instance[key], sub, root, "%s.%s" % (path, key)))
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append("%s: unexpected property %r" % (path, key))
        elif isinstance(schema.get("additionalProperties"), dict):
            for key, val in instance.items():
                if key not in props:
                    errors.extend(validate(val, schema["additionalProperties"], root, "%s.%s" % (path, key)))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append("%s: fewer than %d items" % (path, schema["minItems"]))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append("%s: more than %d items" % (path, schema["maxItems"]))
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], root, "%s[%d]" % (path, index)))
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            matches = [not validate(instance, sub, root, path) for sub in schema[keyword]]
            if keyword == "anyOf" and not any(matches):
                errors.append("%s: matches none of anyOf" % path)
            if keyword == "oneOf" and sum(matches) != 1:
                errors.append("%s: matches %d of oneOf (need exactly 1)" % (path, sum(matches)))
    if "allOf" in schema:
        for sub in schema["allOf"]:
            errors.extend(validate(instance, sub, root, path))
    return errors
