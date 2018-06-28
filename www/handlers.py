# !/usr/bin/python3
# -*- coding: utf-8 -*-
# @Time    : 2018/6/23 9:36
# @Author  : zzj
# @Email   : XX@XX.com
# @File    : handlers.py
# @Software: PyCharm

'url handlers'


import re
import time
import json
import logging
import hashlib
import base64
import asyncio
import markdown2

from aiohttp import web
from coroweb import  get,post
from apis import APIValueError, APIResourceNotFoundError, APIPermissionError, Page
from models import User, Comment, Blog, next_id
from config import configs


COOKIE_NAME = 'awesession'
_COOKIE_KEY = configs.session.secret


def check_admin(request):
	if request.__user__ is None or not request.__user__.admin:
		raise APIPermissionError()


def get_page_index(page_str):
	p = 1
	try:
		p = int(page_str)
	except ValueError as e:
		pass
	if p < 1:
		p = 1
	return p


def user2cookie(user, max_age):
	# build cookie string by : id-expires-sha1
	# 过期时间是当前时间+设置的有效时间
	expires = str(int(time.time() + max_age))
	# 构建cookie存储的信息字符串
	s = '%s-%s-%s-%s' % (user.id, user.passwd, expires, _COOKIE_KEY)
	L = [user.id, expires, hashlib.sha1(s.encode('utf-8')).hexdigest()]
	# 用-隔开，返回
	return '-'.join(L)


def text2html(text):
	lines = map(lambda s: '<p>%s</p>' % s.replace('&', '&amp;').replace('<',
                                                                        '&lt;').replace(
        '>', '&gt;'), filter(lambda s: s.strip() != '', text.split('\n')))
	return ''.join(lines)


async def cookie2user(cookie_str):
	# cookie_str是空则返回
	if not cookie_str:
		return None
	try:
		# 通过‘-’分割字符串
		L = cookie_str.split('-')
		# 如果不是三个元素的话，与我们当初构造sha1字符串时不符，返回None
		if len(L) != 3:
			return None
		# 分别获取到用户id，过期时间和sha1字符串
		uid, expires, sha1 = L
		# 如果超时，返回None
		if int(expires) < time.time():
			return None
		# 根据用户id查找库，对比有没有该用户，没有返回None
		user = await User.find(uid)
		if user is None:
			return None
		# 根据查找到的user的数据构造一个校验sha1字符串
		s = '%s-%s-%s-%s' % (uid, user.passwd, expires, _COOKIE_KEY)
		# 比较cookie里的sha1和校验sha1，一样的话，说明当前请求的用户是合法的。
		if sha1 != hashlib.sha1(s.encode('utf-8')).hexdigest():
			logging.info('invalid sha1')
			return  None
		user.passwd = '******'
		# 返回合法的user
		return user
	except Exception as e:
		logging.exception(e)
		return None


@get('/')
async def index(*, page='1'):
    # 获取到要展示的博客页数是第几页
    page_index = get_page_index(page)
    # 查找博客表里的条目数
    num = await Blog.findNumber('count(id)')
    # 通过Page类来计算当前页的相关信息
    page = Page(num, page_index)
    # 如果表里没有条目，则不需要系那是
    if num == 0:
        blogs = []
    else:
        # 否则，根据计算出来的offset(取的初始条目index)和limit(取的条数)，来取出条目
        blogs = await Blog.findAll(orderBy='created_at desc', limit=(page.offset, page.limit))
        # 返回给浏览器
    return {
        '__template__': 'blogs.html',
        'page': page,
        'blogs': blogs,
	    
    }


@get('/blog/{id}')
async def get_blog(id):
	blog = await Blog.find(id)
	comments = await Comment.findAll('blog_id=?', [id], orderBy='created_at desc')
	for c in comments:
		c.html_content = text2html(c.content)
	blog.html_content = markdown2.markdown(blog.content)
	return {
        '__template__' : 'blog.html',
        'blog' : blog,
        'comments' : comments
    }


# 注册页面
@get('/register')
async def register():
	return {
        '__template__' : 'register.html'
    }

# 登陆界面
@get('/signin')
async def signin():
	return {
        '__template__' : 'signin.html'
    }

# 登出操作
@get('/signout')
async def signout(request):
	referer = request.headers.get('Referer')
	r = web.HTTPFound(referer or '/')
	# 清理掉cookie的用户信息数据
	r.set_cookie(COOKIE_NAME, '-deleted-', max_age=0, httponly=True)
	logging.info('user signed out.')
	return r


# 登陆请求
@post('/api/authenticate')
async def authenticate(*, email, passwd):
	# 如果email或password为空，都说明错误
	if not email:
		raise APIValueError('email', 'Invalid email.')
	if not passwd:
		raise APIValueError('passwd', 'Invalid password.')
	# 根据email在库里查找匹配的用户
	users = await User.findAll('email=?', [email])
	if len(users) == 0:  # 没找到用户，返回用户不存在
		raise APIValueError('email', 'Email not exist')
	# 取第一个查到的用户，理论上就一个
	user = users[0]
	# 按存储密码的方式获取出请求传入的请求传入的密码字段的sha1值
	sha1 = hashlib.sha1()
	sha1.update(user.id.encode('utf-8'))
	sha1.update(b':')
	sha1.update(passwd.encode('utf-8'))
	# 和库里的密码字段的值进行比较，一样的话认证通过，不一样的话，认证失败
	if user.passwd != sha1.hexdigest():
		raise APIValueError('passwd', 'Invalid password.')
	# 构建返回信息
	r = web.Response()
	# 添加cookie
	r.set_cookie(COOKIE_NAME, user2cookie(user, 86400), max_age=86400, httponly=True)
	# 只把返回的实例密码改为******，库里的密码依然正确，以保证真是的密码不会因返回而暴露
	user.passwd = '******'
	# 返回的是json数据，所以把content_type设置为json的
	r.content_type = 'application/json'
	# 把对象转化成json格式返回
	r.body = json.dumps(user, ensure_ascii=False).encode('utf-8')
	return r


# 注册请求
_RE_EMAIL = re.compile(r'^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$')
_RE_SHA1 = re.compile(r'^[0-9a-f]{40}$')

@post('/api/users')
async def api_register_user(*, email, name, passwd):
	# 判断name是否存在，且是否只是‘\n'\r\t这种特殊字符
	if not name or not name.strip():
		raise APIValueError('name')
	# 判断email是否存在，且是否符合轨道的正则表达式
	if not email or not _RE_EMAIL.match(email):
		raise APIValueError('email')
	# 判断passwd 是否存在，且是否符合轨道的正则表达式
	if not passwd or not _RE_SHA1.match(passwd):
		raise APIValueError('passwd')
	# 查一下库里是否有相同的email地址，如果有的话提示用户已被注册
	users = await User.findAll('email=?', [email])
	if len(users) > 0:
		raise APIValueError('regiser:failed', 'email', 'Email is already in use.')
	uid = next_id()  # 生成一个当前要注册用户的唯一uid
	sha1_passwd = '%s:%s' % (uid, passwd)  # 构建sha1_passwd
	# 创建一个用户（密码是通过sha1加密保存）
	user = User(id=uid, name=name.strip(), email=email, passwd=hashlib.sha1(sha1_passwd.encode('utf-8')).hexdigest(), image='http://www.gravatar.com/avatar/%s?d=mm&s=120' % hashlib.md5(email.encode('utf-8')).hexdigest())
	await user.save()  #保存这个用户到数据库用户表
	r = web.Response()  #构建返回信息
	# 添加cookie
	r.set_cookie(COOKIE_NAME, user2cookie(user, 86400), max_age=86400, httponly=True)
	user.passwd = '******'
	r.content_type = 'application/json'
	r.body = json.dumps(user, ensure_ascii=False).encode('utf-8')
	return r


@get('/manage/blogs/create')
async def manage_create_blog():
	return {
        '__template__': 'manage_blog_edit.html',
        'id': '',
        'action': '/api/blogs'
    }


@get('/manage/blogs')
async def manage_blogs(*, page='1'):
	return {
		'__template__' : 'manage_blogs.html',
		'page_index' : get_page_index(page)
    }


@get('/api/blogs')
async def api_blogs(*, page='1'):
	page_index = get_page_index(page)
	num = await Blog.findNumber('count(id)')
	p = Page(num, page_index)
	if num == 0:
		return dict(page=p, blogs=())
	blogs = await Blog.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
	return dict(page=p, blogs=blogs)


@get('/api/blogs/{id}')
async def api_get_blog(*, id):
	blog = await Blog.find(id)
	return blog


@post('/api/blogs')
async def api_create_blog(request, *, name, summary, content):
	check_admin(request)
	if not name or not name.strip():
		raise APIValueError('name', 'name cannot be empty.')
	if not summary or not summary.strip():
		raise APIValueError('summary', 'summary cannot be empty.')
	if not content or not content.strip():
		raise APIValueError('content', 'content cannot be empty.')
	blog = Blog(user_id=request.__user__.id, user_name=request.__user__.name, user_image=request.__user__.image, name=name.strip(), summary=summary.strip(), content=content.strip())
	await blog.save()
	return blog