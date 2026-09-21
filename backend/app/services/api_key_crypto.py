"""API Key 的静态加密。

Windows 上用系统 DPAPI（``CryptProtectData``），密文绑定到当前用户 + 当前机器，密钥
无需自管——这正是本地单用户工具想要的：Key 不再以明文躺在 SQLite 里，但同一用户在同一台
机器上读取时无需任何额外密码。

其他平台保持明文：本项目是本地单用户工具，跨平台钥匙串需要额外依赖（keyring 及其系统
服务），换来的是"非 Windows 上也不明文"，而 Windows 才是主要运行环境。这里刻意不引依赖，
代价是 Linux/macOS 上仍按明文存（与历史行为一致）。

存储格式：``dpapi:v1:`` + base64(密文)。不带前缀的值一律视为历史明文，解密时原样返回，
下次保存时再加密——老库无需迁移，透明升级。
"""
from __future__ import annotations

import base64
import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

_PREFIX = "dpapi:v1:"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _protect(data: bytes) -> bytes:
    data_in = _DATA_BLOB(
        len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char))
    )
    data_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)
    ):
        raise OSError("CryptProtectData 失败")
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(data_out.pbData)


def _unprotect(data: bytes) -> bytes:
    data_in = _DATA_BLOB(
        len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char))
    )
    data_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)
    ):
        raise OSError("CryptUnprotectData 失败")
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(data_out.pbData)


def encrypt_key(plaintext: str) -> str:
    """加密 API Key。空串原样返回；非 Windows 平台保持明文。"""
    if not plaintext:
        return plaintext
    if sys.platform != "win32":
        return plaintext
    try:
        ciphertext = _protect(plaintext.encode("utf-8"))
    except OSError:
        # DPAPI 不可用时退回明文，而不是让用户连设置都保存不了。
        logger.warning("DPAPI 加密失败，API Key 将按明文保存", exc_info=True)
        return plaintext
    return _PREFIX + base64.b64encode(ciphertext).decode("ascii")


def decrypt_key(stored: str) -> str:
    """解密 API Key。空串、以及不带前缀的历史明文，一律原样返回。"""
    if not stored:
        return stored
    if not stored.startswith(_PREFIX):
        return stored
    try:
        ciphertext = base64.b64decode(stored[len(_PREFIX) :].encode("ascii"), validate=True)
    except Exception:
        logger.warning("API Key 密文损坏，无法解密")
        return ""
    if sys.platform != "win32":
        # 非 Windows 读到的 DPAPI 密文无法解（如数据库从 Windows 拷来）；按未配置处理。
        logger.warning("当前平台无法解密 DPAPI 保护的 API Key")
        return ""
    try:
        return _unprotect(ciphertext).decode("utf-8")
    except OSError:
        # Key 属于另一台机器/用户，或系统状态变化；按未配置处理，让用户重新填写。
        logger.warning("DPAPI 解密失败（Key 可能属于另一台机器或用户），按未配置处理")
        return ""
