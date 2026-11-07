"""The file adapter: verified writes, and package-owned errors at the boundary."""

import os
import stat

import pytest

from l3io.wp.config import (
    MISSING,
    ConfigReadError,
    ConfigWriteError,
    ReadBackError,
    WpConfigError,
    WpConfigFile,
    WpConfigString,
)

SOUND = "<?php\ndefine('DB_NAME', 'original');\n$table_prefix = 'wp_';\n"


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_text(SOUND)
    return path


def test_composition_not_inheritance():
    """AD-1: inheritance would put every core method on the adapter's surface."""
    assert not issubclass(WpConfigFile, WpConfigString)


def test_read_and_write_round_trip(config_file):
    config = WpConfigFile(config_file)
    assert config.get("DB_NAME") == "original"
    assert config.set("DB_NAME", "updated") is True
    assert WpConfigFile(config_file).get("DB_NAME") == "updated"


def test_writing_the_same_value_does_not_rewrite(config_file):
    before = config_file.stat().st_mtime_ns
    assert WpConfigFile(config_file).set("DB_NAME", "original") is False
    assert config_file.stat().st_mtime_ns == before


def test_table_prefix_round_trip(config_file):
    config = WpConfigFile(config_file)
    assert config.get_variable("table_prefix") == "wp_"
    assert config.set_variable("table_prefix", "wpfoo_") is True
    assert WpConfigFile(config_file).get_variable("table_prefix") == "wpfoo_"


def test_absent_key_is_missing_not_none(config_file):
    assert WpConfigFile(config_file).get("NOPE") is MISSING


def test_a_failed_read_back_leaves_the_original_untouched(tmp_path):
    """
    A file already carrying a duplicate definition cannot be written safely: the
    pattern matches one occurrence while WordPress uses the other.
    """
    path = tmp_path / "wp-config.php"
    damaged = "<?php\ndefine('DB_NAME', 'a');\ndefine('DB_NAME', 'b');\n"
    path.write_text(damaged)

    config = WpConfigFile(path)
    with pytest.raises(ReadBackError) as caught:
        config.set("DB_NAME", "c")

    assert path.read_text() == damaged, "the original file must survive intact"
    assert any("2 times" in problem for problem in caught.value.mismatches)


def test_no_temporary_file_is_left_behind(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_text("<?php\ndefine('DB_NAME', 'a');\ndefine('DB_NAME', 'b');\n")
    with pytest.raises(ReadBackError):
        WpConfigFile(path).set("DB_NAME", "c")
    assert list(tmp_path.iterdir()) == [path]


def test_a_missing_file_raises_a_package_owned_error(tmp_path):
    """AD-14: no stdlib exception type crosses the public boundary."""
    with pytest.raises(ConfigReadError) as caught:
        WpConfigFile(tmp_path / "absent.php")
    assert isinstance(caught.value, WpConfigError)
    assert not isinstance(caught.value, OSError)
    assert caught.value.__cause__ is not None, "the cause must be chained"


def test_errors_carry_structured_fields(tmp_path):
    with pytest.raises(ConfigReadError) as caught:
        WpConfigFile(tmp_path / "absent.php")
    assert caught.value.filename.endswith("absent.php")
    assert caught.value.reason


def test_every_public_error_descends_from_one_base():
    import l3io.wp.config as package

    errors = [
        getattr(package, name)
        for name in package.__all__
        if isinstance(getattr(package, name), type)
        and issubclass(getattr(package, name), BaseException)
    ]
    assert errors, "the package must export its error hierarchy"
    assert all(issubclass(error, WpConfigError) for error in errors)


def test_a_file_with_no_php_newline_raises_and_leaves_the_file_alone(tmp_path):
    """The same ADR-0010 limit, through the file adapter."""
    from l3io.wp.config import ConfigWriteError

    path = tmp_path / "wp-config.php"
    original = "<?php define('DB_NAME', 'a');\n"
    path.write_text(original)

    with pytest.raises(ConfigWriteError):
        WpConfigFile(path).set("BRAND_NEW", "x")

    assert path.read_text() == original
    assert list(tmp_path.iterdir()) == [path], "no temporary file left behind"


# --- A write must not change who can read the file -------------------------------
#
# wp-config.php holds DB_PASSWORD. v0.1.0 wrote a temp file under the process umask
# and renamed it over the original, so a 0640 file came back 0644 under umask 022:
# world-readable, on every restore that rewrites it.


# Every guarantee below holds for both writers: set(), and replace_content(), which
# backup uses to lay a whole archived config over the target's. Each writer changes
# DB_NAME to 'updated'. Parametrising them is what proves the two share one write.
UPDATED = SOUND.replace("'original'", "'updated'")


@pytest.fixture(params=["set", "replace_content"])
def write(request):
    if request.param == "set":
        return lambda config: config.set("DB_NAME", "updated")
    return lambda config: config.replace_content(UPDATED)


@pytest.fixture
def umask_022():
    previous = os.umask(0o022)
    yield
    os.umask(previous)


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o660, 0o400])
def test_a_write_keeps_the_original_mode(config_file, umask_022, mode, write):
    config_file.chmod(mode)
    assert write(WpConfigFile(config_file)) is True
    assert stat.S_IMODE(config_file.stat().st_mode) == mode


def _a_group_other_than_the_effective_one() -> int:
    """Root (as in CI's container) may chown to any group; anyone else needs a second one."""
    if os.geteuid() == 0:
        return os.getegid() + 4242
    others = [gid for gid in os.getgroups() if gid != os.getegid()]
    if not others:
        pytest.skip("needs root, or membership of a second group")
    return others[0]


def test_a_write_keeps_the_original_group(config_file, write):
    """A group-readable file is only useful while it keeps its group (PHP's)."""
    group = _a_group_other_than_the_effective_one()
    os.chown(config_file, -1, group)
    write(WpConfigFile(config_file))
    assert config_file.stat().st_gid == group


def test_ownership_that_cannot_be_kept_refuses_the_write(config_file, monkeypatch, write):
    """
    Handing the file to the writer could lock PHP out of it, or open it to the
    writer's group. Refuse instead, and leave the original alone.
    """
    group = _a_group_other_than_the_effective_one()
    os.chown(config_file, -1, group)

    def refuse(*_args):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "fchown", refuse)
    with pytest.raises(ConfigWriteError) as caught:
        write(WpConfigFile(config_file))

    assert "owner" in caught.value.reason
    assert config_file.read_text() == SOUND
    assert config_file.stat().st_gid == group
    assert list(config_file.parent.iterdir()) == [config_file]


def test_a_planted_temp_name_is_never_written_through(config_file, write):
    """
    v0.1.0 used the fixed name ``wp-config.php.l3io-tmp``: a symlink planted there
    redirected the write, then was renamed over wp-config.php itself.
    """
    victim = config_file.parent / "victim"
    victim.write_text("untouched")
    decoy = config_file.with_name(f"{config_file.name}.l3io-tmp")
    decoy.symlink_to(victim)

    write(WpConfigFile(config_file))

    assert victim.read_text() == "untouched"
    assert not config_file.is_symlink()
    assert WpConfigFile(config_file).get("DB_NAME") == "updated"
    assert decoy.is_symlink(), "a file the package did not create is not its to remove"


def test_the_write_is_flushed_to_disk_before_and_after_the_rename(config_file, monkeypatch, write):
    """
    Without fsync a crash after the rename can leave an empty or stale file, so the
    temp file must be synced before it replaces the original, and the directory after.
    """
    synced = []
    real_fsync = os.fsync

    def spy(fd):
        synced.append(stat.S_IFMT(os.fstat(fd).st_mode))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    write(WpConfigFile(config_file))
    assert synced == [stat.S_IFREG, stat.S_IFDIR]


def test_a_file_removed_after_reading_is_not_recreated(config_file, write):
    """
    The package never creates a wp-config.php: with no original there is no mode or
    owner to keep, and guessing one for a credentials file is the defect itself.
    """
    config = WpConfigFile(config_file)
    config_file.unlink()

    with pytest.raises(ConfigWriteError):
        write(config)

    assert list(config_file.parent.iterdir()) == []


def test_a_directory_that_cannot_be_synced_still_reports_the_write(
    config_file, monkeypatch, caplog, write
):
    """The rename has happened; raising would report a changed file as unchanged."""
    real_fsync = os.fsync

    def refuse_directories(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(22, "Invalid argument")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", refuse_directories)
    assert write(WpConfigFile(config_file)) is True
    assert WpConfigFile(config_file).get("DB_NAME") == "updated"
    assert "could not sync its directory" in caplog.text


# --- A write changes one value, not the file's line endings ----------------------
#
# WordPress's own wp-config-sample.php and the Docker image's config use CRLF. v0.1.1
# read and wrote in text mode, so every write rewrote every line ending to LF.


def test_a_crlf_file_keeps_its_line_endings(tmp_path):
    path = tmp_path / "wp-config.php"
    original = b"<?php\r\ndefine( 'DB_NAME', 'a' );\r\ndefine( 'DB_USER', 'u' );\r\n"
    path.write_bytes(original)
    WpConfigFile(path).set("DB_NAME", "b")
    assert path.read_bytes() == original.replace(b"'a'", b"'b'")


def test_a_key_is_added_to_a_crlf_file_with_a_crlf(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_bytes(b"<?php\r\ndefine( 'DB_NAME', 'a' );\r\n")
    WpConfigFile(path).set("WP_CACHE", True)
    assert (
        path.read_bytes() == b"<?php\r\ndefine('WP_CACHE', true);\r\ndefine( 'DB_NAME', 'a' );\r\n"
    )


def test_content_is_reported_as_it_is_on_disk(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_bytes(b"<?php\r\ndefine( 'DB_NAME', 'a' );\r\n")
    assert WpConfigFile(path).content == "<?php\r\ndefine( 'DB_NAME', 'a' );\r\n"


# --- replace_content: the whole file, through the same verified write ------------
#
# Backup's --overwrite-wp-config lays the archived config over the target's, with the
# target's DB_* values set in memory first (its ADR-0023). Until v0.1.4 it had to
# copy this package's temp-fsync-replace write to do that; now it calls this one.


def test_replace_content_writes_exactly_the_text_given(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_bytes(b"<?php\r\ndefine( 'DB_NAME', 'a' );\r\n")
    new = "<?php\r\ndefine( 'DB_NAME', 'b' );\r\ndefine( 'WP_CACHE', true );\r\n"
    config = WpConfigFile(path)
    assert config.replace_content(new) is True
    assert path.read_bytes() == new.encode(), "byte for byte, CRLF included"
    assert config.content == new
    assert config.get("WP_CACHE") is True


def test_replace_content_with_the_same_text_does_not_rewrite(config_file):
    before = config_file.stat().st_mtime_ns
    assert WpConfigFile(config_file).replace_content(SOUND) is False
    assert config_file.stat().st_mtime_ns == before


def test_replace_content_refuses_text_with_a_duplicate_definition(config_file):
    """PHP keeps the first and warns; the scanner would read one and write the other."""
    doubled = SOUND + "define('DB_NAME', 'again');\n"
    with pytest.raises(ReadBackError) as caught:
        WpConfigFile(config_file).replace_content(doubled)
    assert any("2 times" in problem for problem in caught.value.mismatches)
    assert config_file.read_text() == SOUND
    assert list(config_file.parent.iterdir()) == [config_file]


@pytest.mark.parametrize("bad", [b"<?php\n", None, 42], ids=["bytes", "none", "int"])
def test_replace_content_refuses_what_is_not_text(config_file, bad):
    """AD-14: a TypeError from deep inside must not cross the public boundary."""
    with pytest.raises(ConfigWriteError):
        WpConfigFile(config_file).replace_content(bad)
    assert config_file.read_text() == SOUND


def test_replace_content_refuses_text_no_file_can_hold(config_file):
    with pytest.raises(ConfigWriteError):
        WpConfigFile(config_file).replace_content("<?php\ndefine('X', '\udcff');\n")
    assert config_file.read_text() == SOUND
    assert list(config_file.parent.iterdir()) == [config_file]
