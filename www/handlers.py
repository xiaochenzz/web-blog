# !/usr/bin/python3
# -*- coding: utf-8 -*-
# @Time    : 2018/6/23 9:36
# @Author  : zzj
# @Email   : XX@XX.com
# @File    : handlers.py
# @Software: PyCharm

'url handlers'

from coroweb import  get
import asyncio


@get('/')
async def index(request):
	return '<h1>Awesome</h1>'


@get('/hello')
async def hello(request):
	return '<h1>hello!</h1>'