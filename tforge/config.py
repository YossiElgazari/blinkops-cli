import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from tforge.errors import ConfigError

DEFAULT_URL = "https://integrations-assignment-ticketforge.vercel.app"


@dataclass
class Config:
    url: str
    username: str
    password: str


def config_path() -> Path:
    override = os.environ.get("TFORGE_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".tforge" / "config.json"


def read_config_file() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config file {path} is not valid JSON. Run `tforge setup` again.") from exc


def load_config() -> Config:
    data = read_config_file()
    url = os.environ.get("TFORGE_URL") or data.get("url") or DEFAULT_URL
    username = os.environ.get("TFORGE_USERNAME") or data.get("username")
    password = os.environ.get("TFORGE_PASSWORD") or data.get("password")
    if not username or not password:
        raise ConfigError("tforge is not configured. Run `tforge setup` first.")
    return Config(url=url.rstrip("/"), username=username, password=password)


def save_config(config: Config) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    # The password is stored in plain text (Basic auth needs it on every call), so keep the file owner-only.
    path.chmod(0o600)
    return path


def validate_username(username: str) -> None:
    if ":" in username:
        raise ConfigError("Username cannot contain ':' because HTTP Basic auth splits on it.")
    if len(username) < 3:
        raise ConfigError("Username must be at least 3 characters.")
