#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @Time    : 2018/6/9 23:52
# @Author  : zzj
# @Email   : zhongjv@163.com
# @File    : test.py
# @Software: PyCharm


import www.orm
from www.models import User,Blog,Comment
import asyncio

async def test():

    #创建连接池,里面的host,port,user,password需要替换为自己数据库的信息
    await www.orm.create_pool(loop=loop, host='localhost', port=3306, user='root', password='',db='awesome')

    #没有设置默认值的一个都不能少
    u = User(name='12223', email='d21@qq.com', passwd='0123', image='about:blank',id='1110')

    await u.save()

# 获取EventLoop:
loop = asyncio.get_event_loop()

#把协程丢到EventLoop中执行
loop.run_until_complete(test())

#关闭EventLoop
loop.close()

'sql check code'
import mysql.connector

conn=mysql.connector.connect(user='root', password='', database='awesome')
cursor=conn.cursor()
cursor.execute('select * from users')
data=cursor.fetchall()
print(data)