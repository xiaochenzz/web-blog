# !/usr/bin/python3
# -*- coding: utf-8 -*-
# @Time    : 2018/6/22 16:20
# @Author  : zzj
# @Email   : XX@XX.com
# @File    : coroweb.py
# @Software: PyCharm


import asyncio
import os
import inspect
import logging
import functools

from urllib import parse
from aiohttp import web
from www.apis import APIError

def get(path)