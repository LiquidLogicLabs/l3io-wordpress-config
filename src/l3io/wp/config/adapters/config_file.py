"""
The I/O shell around the pure core: a ``wp-config.php`` on disk.

Holds a :class:`WpConfigString` rather than subclassing it (AD-1). Inheritance
would put every core method on this class automatically, so the surface declared
by ``__all__`` could not bound it.
"""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Callable
from logging import getLogger
from pathlib import Path

from l3io.wp.config.core.config_string import Kind, WpConfigString
from l3io.wp.config.core.verification import verify_write
from l3io.wp.config.domain.errors import ConfigReadError, ConfigWriteError, ReadBackError
from l3io.wp.config.domain.values import ConfigValue, MissingType

__all__ = ["WpConfigFile"]

_log = getLogger(__name__)


class WpConfigFile:
    """
    Read and write ``define()`` constants in a ``wp-config.php`` file.

    Every :meth:`set` is verified by reading the result back before it is
    committed (ADR-0010). Verification failure leaves the original file
    untouched and raises :class:`ReadBackError`.

    Args:
        filename: Path to the ``wp-config.php`` file.

    Raises:
        ConfigReadError: The file cannot be read.
    """

    def __init__(self, filename: str | os.PathLike[str]) -> None:
        try:
            self._path = Path(filename)
        except TypeError as exc:
            raise ConfigReadError(filename=repr(filename), reason=str(exc)) from exc
        self._config = WpConfigString(self._read())

    @property
    def filename(self) -> str:
        """The path this instance reads and writes."""
        return str(self._path)

    @property
    def content(self) -> str:
        """The current content, including changes made by :meth:`set`."""
        return self._config.content

    def get(self, key: str) -> ConfigValue | MissingType:
        """
        The value of ``key``, or :data:`MISSING` if it is not defined.

        A key defined as ``false``, ``0`` or ``''`` is present and falsy, so test
        ``result is MISSING`` rather than truthiness.
        """
        return self._config.get(key)

    def set(self, key: str, value: ConfigValue) -> bool:
        """
        Set the ``define()`` constant ``key`` in the file, adding it if absent.

        Returns ``True`` if the file was changed, ``False`` if it already held
        this value -- in which case the file is not rewritten.

        Raises:
            ConfigValueError: ``value`` cannot be rendered as a PHP literal.
            ConfigWriteError: The file cannot be written.
            ReadBackError: The result did not verify; the file is unchanged.
        """
        return self._set("define", key, value)

    def get_variable(self, key: str) -> ConfigValue | MissingType:
        """
        The value of the file-scope variable ``key`` (named without its ``$``).

        ``$table_prefix`` is the one WordPress requires; a non-default prefix
        means site metadata is not in ``wp_options``.
        """
        return self._config.get_variable(key)

    def set_variable(self, key: str, value: ConfigValue) -> bool:
        """Set the file-scope variable ``key``, verified the same way as a define."""
        return self._set("variable", key, value)

    def replace_content(self, content: str) -> bool:
        """
        Replace the whole file with ``content``, through the same verified write as :meth:`set`.

        For laying a complete ``wp-config.php`` over this one, such as a restored
        site's own config with this site's credentials already set in it. The text is
        written exactly as given, line endings included. The write keeps the file's
        mode and owner, refuses rather than change its owner, syncs the file and its
        directory, and never leaves a partial file. It is read back before it replaces
        the original, and it is refused if the text defines any key twice: PHP keeps
        the first and warns, and :meth:`set` could then change the wrong one.

        Returns ``True`` if the file was replaced, ``False`` if it already held this
        text -- in which case it is not rewritten.

        Raises:
            ConfigWriteError: ``content`` is not a ``str``, cannot be encoded, or the
                file cannot be written; the file is unchanged.
            ReadBackError: The text defines a key twice, or did not read back as
                written; the file is unchanged.
        """
        if not isinstance(content, str):
            raise ConfigWriteError(
                filename=str(self._path),
                reason=f"content must be str, not {type(content).__name__}",
            )
        if content == self._config.content:
            _log.debug("%s already holds this content; not rewriting.", self._path)
            return False
        try:
            actual = self._replace_verified(
                content, lambda actual: verify_write(before=content, actual=actual, written={})
            )
        # ValueError is UnicodeEncodeError, as in _set.
        except (OSError, ValueError) as exc:
            raise ConfigWriteError(filename=str(self._path), reason=str(exc)) from exc

        self._config = WpConfigString(actual)
        _log.debug("%s replaced and verified.", self._path)
        return True

    def _set(self, kind: Kind, key: str, value: ConfigValue) -> bool:
        before = self._config.content
        working = WpConfigString(before)
        mutate = working.set if kind == "define" else working.set_variable
        if not mutate(key, value):
            _log.debug("%r already up to date in %s; not rewriting.", key, self._path)
            return False

        intended = working.content
        try:
            actual = self._replace_verified(
                intended,
                lambda actual: verify_write(
                    before=before, actual=actual, written={(kind, key): value}
                ),
            )
        # ValueError is UnicodeEncodeError: a str can hold a lone surrogate that
        # no UTF-8 file can.
        except (OSError, ValueError) as exc:
            raise ConfigWriteError(filename=str(self._path), reason=str(exc), key=key) from exc

        self._config = WpConfigString(actual)
        _log.debug("%r written to %s and verified.", key, self._path)
        return True

    def _replace_verified(self, intended: str, problems_in: Callable[[str], list[str]]) -> str:
        """
        Write ``intended`` beside the file, verify it, then rename it over the file.

        The temp file is created by ``mkstemp``: an unpredictable name, opened
        exclusively, so nothing planted in the site directory is written through, and
        mode 0600 until it takes the original's mode and owner. The file holds
        DB_PASSWORD, so a write must never widen who can read it, and an owner that
        cannot be kept refuses the write rather than handing the file to the writer.
        There is no original to copy from when the file is gone, so the package never
        creates one. Both the file and its directory are synced, so a crash leaves
        either the old content or the new, never an empty file.
        """
        original = self._path.stat()
        directory = self._path.parent
        fd, name = tempfile.mkstemp(
            dir=directory, prefix=f".{self._path.name}.", suffix=".l3io-tmp"
        )
        tmp = Path(name)
        committed = False
        try:
            # newline="": no translation either way, so a CRLF file stays CRLF.
            with os.fdopen(fd, "w+", encoding="utf-8", newline="") as handle:
                self._take_ownership(handle.fileno(), name, original)
                handle.write(intended)
                handle.flush()
                os.fsync(handle.fileno())
                # Read back from the temp file, so a failure never touches the original.
                handle.seek(0)
                actual = handle.read()
            problems = problems_in(actual)
            if problems:
                raise ReadBackError(filename=str(self._path), mismatches=problems)
            tmp.replace(self._path)
            committed = True
            _fsync_directory(directory)
        finally:
            if not committed:
                # Best-effort cleanup; the write already failed.
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:  # pragma: no cover - cleanup must not mask the outcome
                    _log.warning("Could not remove temporary file %s", tmp)
        return actual

    def _take_ownership(self, fd: int, name: str, original: os.stat_result) -> None:
        """Give the temp file the original's owner, then its mode (chown can clear setgid)."""
        fchown = getattr(os, "fchown", None)
        if fchown is not None:
            current = os.fstat(fd)
            if (current.st_uid, current.st_gid) != (original.st_uid, original.st_gid):
                try:
                    fchown(fd, original.st_uid, original.st_gid)
                except PermissionError as exc:
                    raise PermissionError(
                        exc.errno,
                        f"cannot keep the file's owner {original.st_uid}:{original.st_gid}"
                        " (run as that owner, or as root); the file was not changed",
                    ) from exc
        mode = stat.S_IMODE(original.st_mode)
        if os.chmod in os.supports_fd:
            os.fchmod(fd, mode)
        else:  # pragma: no cover - Windows
            Path(name).chmod(mode)

    def verify(self) -> None:
        """
        Re-read the file and check it is internally sound.

        Raises:
            ConfigReadError: The file cannot be read.
            ReadBackError: The file contains duplicate definitions, or has
                diverged from the content this instance last wrote.
        """
        actual = self._read()
        problems = verify_write(before=self._config.content, actual=actual, written={})
        if problems:
            raise ReadBackError(filename=str(self._path), mismatches=problems)

    def _read(self) -> str:
        try:
            # newline="": what is on disk, CRLF included. Text mode would turn every
            # CRLF into LF, and the next write would rewrite every line of the file.
            with self._path.open(encoding="utf-8", newline="") as handle:
                return handle.read()
        # ValueError covers both a file that is not UTF-8 (UnicodeDecodeError) and
        # a path carrying a NUL byte, which the OS layer rejects before any I/O.
        except (OSError, ValueError) as exc:
            raise ConfigReadError(filename=str(self._path), reason=str(exc)) from exc


def _fsync_directory(directory: Path) -> None:
    """
    Make the rename durable.

    The rename has already happened, so a failure here is logged rather than raised:
    raising would report a changed file as unchanged. Some filesystems refuse to sync
    a directory at all, and platforms with no directory handle have nothing to sync.
    """
    flag = getattr(os, "O_DIRECTORY", None)
    if flag is None:  # pragma: no cover - Windows
        return
    try:
        fd = os.open(directory, os.O_RDONLY | flag)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        _log.warning("Wrote %s, but could not sync its directory: %s", directory, exc)
