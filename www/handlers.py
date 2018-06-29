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
from coroweb import  get, post
from apis import APIValueError, APIResourceNotFoundError, APIPermissionError, Page
from models import User, Comment, Blog, next_id
from config import configs


COOKIE_NAME = 'awesession'
_COOKIE_KEY = configs.session.secret


# 检测当前用户是不是admin用户
def check_admin(request):
	if request.__user__ is None or not request.__user__.admin:
		raise APIPermissionError()


# 获取页数，主要是做一些容错处理
def get_page_index(page_str):
	p = 1
	try:
		p = int(page_str)
	except ValueError as e:
		pass
	if p < 1:
		p = 1
	return p


# 根据用户信息拼接一个cookie字符串
def user2cookie(user, max_age):
	# build cookie string by : id-expires-sha1
	# 过期时间是当前时间+设置的有效时间
	expires = str(int(time.time() + max_age))
	# 构建cookie存储的信息字符串
	s = '%s-%s-%s-%s' % (user.id, user.passwd, expires, _COOKIE_KEY)
	L = [user.id, expires, hashlib.sha1(s.encode('utf-8')).hexdigest()]
	# 用-隔开，返回
	return '-'.join(L)


# 把纯文本文件转为html格式的文本
def text2html(text):
	lines = map(lambda s: '<p>%s</p>' % s.replace('&', '&amp;').replace('<',
                                                                        '&lt;').replace(
        '>', '&gt;'), filter(lambda s: s.strip() != '', text.split('\n')))
	return ''.join(lines)


# 根据cookie字符串，解析出用户信息相关的内容
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


# 首页，会显示博客列表
@get('/')
async def index(*, page='1'):
	# 获取到要展示的博客页数是第几页
	page_index = get_page_index(page)
	# 查找博客表里的条目数
	num = await Blog.findNumber('count(id)')
	# 通过Page类来计算当前页的相关信息
	page = Page(num, page_index)
	# 如果表里没有条目，没有日志
	if num == 0:
		blogs = []
	else:
		# 否则，根据计算出来的offset(取的初始条目index)和limit(取的条数)，来取出条目
		blogs = await Blog.findAll(orderBy='created_at desc', limit=(page.offset, page.limit))
		# 返回给浏览器
	return {
        '__template__': 'blogs.html',
        'page': page,
        'blogs': blogs
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


#-------------------------------------评论管理-------------------------------------------------
# 评论管理页面
@get('/manage')
async def manage():
	return 'redirect:/manage/comments'


@get('/manage/comments')
async def manage_comments(*, page='1'):
	# 查看所有评论
	return {
		'__template__' : 'manage_comments.html',
		'page_index' : get_page_index(page)
	}


@get('/api/comments')
async def api_comments(*, page='1'):
	# 根据page获取评论
	page_index = get_page_index(page)
	num = await Comment.findNumber('count(id)')
	p = Page(num, page_index)
	if num == 0:
		return dict(page=p, comments=())
	comments = await Comment.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
	return dict(page=p, comments=comments)


@post('/api/blogs/{id}/comments')
async def api_create_comment(id, request, *, content):
	# 对某个博客发表评论
	user = request.__user__
	# 必须在登陆状态下评论
	if user is None:
		raise APIPermissionError('content')
	# 评论不能为空
	if not content or not content.strip():
		raise APIValueError('content')
	# 查询以下博客id是否有对应的博客
	blog = await Blog.find(id)
	# 没有的话抛出错误
	if blog is None:
		raise APIResourceNotFoundError('Blog')
	# 构建一条评论
	comment = Comment(blog_id=blog.id, user_id=user.id, user_name=user.name, user_image=user.image, content=content.strip())
	# 保存到评论表里
	await comment.save()
	return comment


@post('/api/comments/{id}/delete')
async def api_delete_comments(id, request):
	# 删除某个评论
	logging.info(id)
	# 检查是否为管理员操作，只有管理员才有权限
	check_admin(request)
	# 查询评论id是否有对应的评论
	c = await Comment.find(id)
	if c is None:
		raise APIResourceNotFoundError('Comment')
	await c.remove()
	return dict(id=id)


# -------------------------------用户管理-----------------------------------------

@get('/show_all_users')
async def show_all_users():
	# 显示所有的用户
	users = await User.findAll()
	logging.info('to index....')
	return {
		'__template__': 'test.html',
		'users': users
	}


@get('/api/users')
async def api_get_users(request):
	# 返回所有的用户信息json格式
	users = await User.findAll(orderBy='created_at desc')
	logging.info('users = %s and type = %s' % (users, type(users)))
	for u in  users:
		u.passwd = '******'
	return dict(users=users)


@get('/manage/users')
async def manage_users(*, page='1'):
	return {
		'__template__': 'manage_users.html',
		'page_index' :get_page_index(page)
	}


# -----------------------------------博客管理处理函数

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


@get('/blog/{id}')
async def get_blog(id):
	# 根据博客ID查询该博客信息
	blog = await Blog.find(id)
	# 根据博客id查询该条博客的评论
	comments = await Comment.findAll('blog_id=?', [id], orderBy='created_at desc')
	for c in comments:
		c.html_content = text2html(c.content)
	blog.html_content = markdown2.markdown(blog.content)
	return {
        '__template__' : 'blog.html',
        'blog' : blog,
        'comments' : comments
    }


@get('/api/blogs/{id}')
async def api_get_blog(*, id):
	blog = await Blog.find(id)
	return blog


@post('/api/blogs/{id}/delete')
async def api_delete_blog(id, request):
	# 删除一条博客
	logging.info("删除博客的博客ID为：%s" % id)
	# 先检查是否是管理员操作，只有管理员才有删除评论权限
	check_admin(request)
	# 查询一下评论id是否有对应的评论
	b = await Blog.find(id)
	# 没有的话抛出错误
	if b is None:
		raise APIResourceNotFoundError('Comment')
	# 有的话删除
	await b.remove()
	return dict(id=id)


@post('/api/blogs/modify')
async def api_modify_blog(request, *, id, name, summary, content):
	# 修改一条博客
	logging.info("修改的博客的博客ID为：%s", id)
	# name，summary,content 不能为空
	if not name or not name.strip():
		raise APIValueError('name', 'name cannot be empty')
	if not summary or not summary.strip():
		raise APIValueError('summary', 'summary cannot be empty')
	if not content or not content.strip():
		raise APIValueError('content', 'content cannot be empty')

	# 获取指定id的blog数据
	blog = await Blog.find(id)
	blog.name = name
	blog.summary = summary
	blog.content = content

	# 保存
	await blog.update()
	return blog


@get('/manage/blogs/modify/{id}')
async def manage_modify_blog(id):
	# 修改博客的页面
	return {
        '__template__': 'manage_blog_modify.html',
        'id': id,
        'action': '/api/blogs/modify'
    }
