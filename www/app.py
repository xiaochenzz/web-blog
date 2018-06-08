# !/usr/bin/python3
# -*- coding: utf-8 -*-
# @Time    : 2018/6/8 14:13
# @Author  : zzj
# @Email   : XX@XX.com
# @File    : app.py.py
# @Software: PyCharm


import logging
logging.basicConfig(level=logging.INFO)

import asyncio
import os
import json
import time

from aiohttp import web


def index(request):
    return web.Response(body=b'<h1>Awesome</h1>', content_type='text/html')


async def init(loop):
    app = web.Application(loop=loop)
    app.router.add_route('GET', '/', index)
    srv = await loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    logging.info('server started at http://127.0.0.1:9000...')
    return srv

loop = asyncio.get_event_loop()
loop.run_until_complete(init(loop))
loop.run_forever()
