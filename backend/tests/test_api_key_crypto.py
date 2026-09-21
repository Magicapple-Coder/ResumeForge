"""API Key 静态加密的单元测试。

roundtrip 类断言跨平台成立：Windows 上走 DPAPI，非 Windows 上 ``encrypt_key`` 是恒等
（保持明文）。前缀与密文形态的断言只在 Windows 上成立。
"""
import sys

import pytest

from app.services.api_key_crypto import decrypt_key, encrypt_key


@pytest.mark.parametrize(
    "key",
    [
        "sk-abc123",
        "密钥-测试",
        "key with spaces and 中文 and 🔑",
        "a" * 500,
    ],
)
def test_roundtrip(key: str) -> None:
    assert decrypt_key(encrypt_key(key)) == key


def test_empty_key_is_left_alone() -> None:
    assert encrypt_key("") == ""
    assert decrypt_key("") == ""


def test_legacy_plaintext_passes_through() -> None:
    # 不带 dpapi:v1: 前缀的历史明文，解密时应原样返回，保证老库无需迁移。
    assert decrypt_key("sk-legacy-plain") == "sk-legacy-plain"
    assert decrypt_key("key-without-prefix") == "key-without-prefix"


def test_corrupted_ciphertext_returns_empty() -> None:
    assert decrypt_key("dpapi:v1:not-valid-base64") == ""


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI 只在 Windows 上生效")
def test_windows_encrypts_with_prefix() -> None:
    encrypted = encrypt_key("sk-abc123")
    assert encrypted.startswith("dpapi:v1:")
    assert encrypted != "sk-abc123"
    # 密文不该包含明文。
    assert "sk-abc123" not in encrypted
