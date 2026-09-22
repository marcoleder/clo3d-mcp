"""Result contracts shared by the stdlib-only CLO bridge and test clients."""

import os

FAILURE_FLAGS = frozenset({
    "opened", "saved", "exported", "imported", "created", "copied",
    "deleted", "simulated", "added", "replaced", "assigned", "set",
})


class OperationOutcomeUnknown(RuntimeError):
    """A native mutation ran, but its resulting state could not be verified."""


def same_project_path(actual, expected):
    if not actual or not expected:
        return False
    try:
        return os.path.samefile(actual, expected)
    except OSError:
        return (os.path.normcase(os.path.realpath(actual))
                == os.path.normcase(os.path.realpath(expected)))


def export_paths(value):
    """Normalize a path, flat paths or nested colorway/view groups.

    Reject invalid leaves instead of dropping them and concealing partial output.
    An empty group is allowed, but the complete result must contain a path.
    """
    paths = []

    def visit(item):
        if isinstance(item, str):
            if not item.strip():
                raise ValueError("CLO returned an empty output path")
            paths.append(item)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
        else:
            raise ValueError("CLO returned an invalid output path")

    visit(value)
    if not paths:
        raise ValueError("CLO returned no output paths")
    return paths
