"""Tests for how the app finds the version shown in the page footer."""
import config


def test_app_version_env_wins( monkeypatch, tmp_path ):
	version_file = tmp_path / ".app-version"
	version_file.write_text( "abc1234 2026-01-01\n" )
	monkeypatch.setattr( config, "VERSION_FILE", version_file )
	monkeypatch.setenv( "APP_VERSION", "manual" )
	assert config._detect_app_version() == "manual"


def test_app_version_from_deploy_file( monkeypatch, tmp_path ):
	version_file = tmp_path / ".app-version"
	version_file.write_text( "abc1234 2026-01-01\n" )
	monkeypatch.setattr( config, "VERSION_FILE", version_file )
	monkeypatch.delenv( "APP_VERSION", raising = False )
	assert config._detect_app_version() == "abc1234 2026-01-01"


def test_app_version_falls_back_to_git( monkeypatch, tmp_path ):
	monkeypatch.setattr( config, "VERSION_FILE", tmp_path / "missing" )
	monkeypatch.delenv( "APP_VERSION", raising = False )
	version = config._detect_app_version()
	assert version != "" and version != "abc1234 2026-01-01"
