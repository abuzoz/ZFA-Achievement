"""Single source of truth for the app version.

Bump this with every GitHub release and keep it equal to the release tag
(without the leading "v"). The updater compares it against the latest release
tag to decide whether a newer build is available.
"""

APP_VERSION = "1.3"
