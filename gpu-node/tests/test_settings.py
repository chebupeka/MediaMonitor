from __future__ import annotations

import pytest

from mm_embeddings.settings import ConfigError, Settings


def test_defaults() -> None:
    s = Settings.from_env({"EMBEDDINGS_TOKEN": "x" * 32, "EMBEDDINGS_MODEL": "", "EMBEDDINGS_PORT": ""})
    assert (s.model, s.device, s.port, s.host, s.batch_size, s.fp16) == (
        "sergeyzh/BERTA",
        "auto",
        8090,
        "0.0.0.0",
        64,
        True,
    )


@pytest.mark.parametrize("token", ["", "   ", "short"])
def test_token_is_required(token: str) -> None:
    with pytest.raises(ConfigError, match="EMBEDDINGS_TOKEN"):
        Settings.from_env({"EMBEDDINGS_TOKEN": token})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EMBEDDINGS_DEVICE", "gpu"),
        ("EMBEDDINGS_PORT", "80800"),
        ("EMBEDDINGS_BATCH_SIZE", "много"),
        ("EMBEDDINGS_FP16", "может быть"),
    ],
)
def test_bad_values_are_explained(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        Settings.from_env({"EMBEDDINGS_TOKEN": "x" * 32, name: value})


def test_overrides() -> None:
    s = Settings.from_env(
        {
            "EMBEDDINGS_TOKEN": "x" * 32,
            "EMBEDDINGS_DEVICE": "CPU",
            "EMBEDDINGS_PORT": "9000",
            "EMBEDDINGS_BATCH_SIZE": "128",
            "EMBEDDINGS_FP16": "false",
            "EMBEDDINGS_HOST": "127.0.0.1",
        }
    )
    assert (s.device, s.port, s.batch_size, s.fp16, s.host) == ("cpu", 9000, 128, False, "127.0.0.1")
