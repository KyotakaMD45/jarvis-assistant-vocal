"""Interactive prompt that asks for an AI API key and saves it to .env."""
from __future__ import annotations

from jarvis.api_key import clean_key, get_api_key, looks_like_key, mask, save_api_key
from jarvis.logger import get_logger
from jarvis.providers import PROVIDERS, create
from jarvis.providers.base import BrainError

log = get_logger(__name__)

MAX_ATTEMPTS = 3


def _verify_online(provider: str, key: str, cfg: dict) -> tuple[bool | None, str]:
    """True = valid, False = rejected, None = could not check (offline, etc.)."""
    label = PROVIDERS[provider].label
    try:
        client = create(provider, cfg["ai"], key)
        if provider == "claude":
            try:
                client.client.models.list(limit=1)
            except Exception as exc:  # noqa: BLE001
                from jarvis.providers.claude import friendly_error

                raise friendly_error(exc) from exc
        else:
            client.available_models()
        return True, f"key accepted by {label}"
    except BrainError as err:
        if err.kind in ("auth", "permission"):
            return False, f"{label} rejected this key"
        return None, f"could not verify the key right now ({err.kind})"
    except Exception as exc:  # noqa: BLE001
        return None, f"could not verify the key right now ({exc.__class__.__name__})"


def setup_key(cfg: dict, provider: str = "claude", only_if_missing: bool = False) -> int:
    if provider not in PROVIDERS:
        print(f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}.")
        return 1
    info = PROVIDERS[provider]
    existing, source = get_api_key(provider)
    if only_if_missing and existing and source == ".env":
        print(f"A {info.label} API key is already saved in .env ({mask(existing)}). "
              f"Use `start.bat --setup-key {provider}` to change it.")
        return 0

    print(f"\n{info.label} API key")
    print(f"Create one at {info.keys_url} (it starts with '{info.key_prefix}').")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = input("Paste your API key and press Enter (or just Enter to skip): ")
        except (EOFError, KeyboardInterrupt):
            print(f"\nSkipped. You can add the key later with `start.bat --setup-key {provider}`.")
            return 1
        key = clean_key(raw)
        if not key:
            print(f"Skipped. You can add the key later with `start.bat --setup-key {provider}`.")
            return 1
        if not looks_like_key(key, provider):
            print(f"  This does not look like a {info.label} API key (it must start with '{info.key_prefix}'). "
                  f"Attempt {attempt}/{MAX_ATTEMPTS}.")
            continue
        valid, detail = _verify_online(provider, key, cfg)
        if valid is False:
            print(f"  {detail}. Check that you copied the whole key. Attempt {attempt}/{MAX_ATTEMPTS}.")
            log.warning("Key setup: %s key rejected by the API", provider)
            continue
        save_api_key(key, provider)
        log.info("Key setup: %s key saved to .env (%s)", provider, mask(key))
        if valid:
            print(f"  OK: {detail}. Saved to .env.")
        else:
            print(f"  Saved to .env, but {detail}. Run test.bat once you are online.")
        if provider != "claude":
            print(f"  Say \"Jarvis, passe sur {info.label}\" to use it.")
        return 0
    print(f"Too many invalid attempts. Run `start.bat --setup-key {provider}` to try again.")
    return 1
