# -*- coding: utf-8 -*-
import binascii
import hashlib
import random
import time

_A1_CHARSET = "abcdefghijklmnopqrstuvwxyz1234567890"


def generate_a1() -> str:
    ts_hex = hex(int(time.time() * 1000))[2:]
    random_str = "".join(random.choices(_A1_CHARSET, k=30))
    a_part = ts_hex + random_str + "5" + "0" + "000"
    crc = binascii.crc32(a_part.encode()) & 0xFFFFFFFF
    return (a_part + str(crc))[:52]


def generate_web_id(a1: str) -> str:
    return hashlib.md5(a1.encode()).hexdigest()
