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

'''
Http定义了与服务器交互的不同方法，最基本的方法有4种，分别是GET，POST，PUT，DELETE。URL全称是资源描述符，
我们可以这样认为：一个URL地址，它用于描述一个网络上的资源，而HTTP中的GET，POST，PUT，DELETE就对应着对这个资源的查，改，增，删4个操作。
建议：
1、get方式的安全性较Post方式要差些，包含机密信息的话，建议用Post数据提交方式；
2、在做数据查询时，建议用Get方式；而在做数据添加、修改或删除时，建议用Post方式；
'''
# 建立视图函数装饰器，用来存储、附带URL信息
def get(path):
	'''
	Define decorator @get('/path')
	'''
	def decorator(func):
		@functools.wraps(func)
		def wrapper(*args, **kw):
			return func(*args, **kw)
		wrapper.__method__ = 'GET'
		wrapper.__route__ = path
		return wrapper
	return decorator

def post(path):

	def decorator(func):
		@functools.wraps(func)
		def wrapper(*args, **kw):
			return func(*args, **kw)
		wrapper.__method__ = 'POST'
		wrapper.__route__ = path
		return wrapper
	return decorator


# 使用inspect模块，检查视图函数的参数

# inspect.Parameter.kind 类型：
# POSITIONAL_ONLY          位置参数
# KEYWORD_ONLY             命名关键词参数
# VAR_POSITIONAL           可选参数 *args
# VAR_KEYWORD              关键词参数 **kw
# POSITIONAL_OR_KEYWORD    位置或必选参数

def get_required_kw_args(fn):  # 获取无默认值的命名关键词参数
	args = []
	'''
	def foo(a, b = 10, *c, d,**kw): pass
	sig = inspect.signature(foo) ==> <Signature (a, b=10, *c, d, **kw)>
	sig.parameters ==>  mappingproxy(OrderedDict([('a', <Parameter "a">), ...]))
	sig.parameters.items() ==> odict_items([('a', <Parameter "a">), ...)])
	sig.parameters.values() ==>  odict_values([<Parameter "a">, ...])
	sig.parameters.keys() ==>  odict_keys(['a', 'b', 'c', 'd', 'kw'])
	'''
	params = inspect.signature(fn).parameters
	for name, param in params.items():
		# 如果视图函数存在命名关键字参数，且默认值为空，获取它的key（参数名）
		if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
			args.append(name)
	return tuple(args)


def get_named_kw_args(fn):  # 获取命名关键词参数
	args = []
	params = inspect.signature(fn).parameters
	for name, param in params.items():
		if param.kind == inspect.Parameter.KEYWORD_ONLY:
			args.append(name)
	return tuple(args)


def has_named_kw_args(fn):  # 判断是否有命名关键词参数
	params = inspect.signature(fn).parameters
	for name, param in params.items():
		if param.kind == inspect.Parameter.KEYWORD_ONLY:
			return True


def has_var_kw_arg(fn):  # 判断是否有关键词参数
	params = inspect.signature(fn).parameters
	for name, param in params.items():
		if param.kind == inspect.Parameter.VAR_KEYWORD:
			return True

def has_request_arg(fn):  # 判断是否含有名叫‘request’的参数，且位置在最后
	sig = inspect.signature(fn)
	params = sig.parameters
	found = False
	for name, param in params.items():
		if name == 'request':
			found = True
			continue
		if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and
		              param.kind != inspect.Parameter.KEYWORD_ONLY and
		              param.kind != inspect.Parameter.VAR_KEYWORD):
			# 若判断为True，表明param只能是位置参数，且该参数位于request之后，故不满足条件，报错。
			raise ValueError('request parameter must be the last named '
			                 'parameter in function:%s%s' % (fn.__name__,
			                                                 str(sig)))
	return found


# 定义RequestHandler从视图函数中分析其需要接受的参数，从web.Request中获取必要的参数
# 调用视图函数，然后把结果转换为web.Response对象，符合aiohttp框架要求
class RequestHandler(object):
	
	'''
	request是经aiohttp包装后的对象。其本质是一个HTTP请求。
	由请求状态（status）、请求首部（header）、内容实体（body）三部分组成。
	我们需要的参数包含在内容实体以及请求状态URI中。
	request对象封装了HTTP请求，可以通过request的属性调取值。
	RequestHandler需要处理以下问题：
	1、确定HTTP请求的方法（’POST’or’GET’）（用request.method获取）
	2、根据HTTP请求的content_type字段，选用不同解析方法获取参数。（用request.content_type获取）
	3、将获取的参数经处理，使其完全符合视图函数接收的参数形式
	4、调用视图函数
	'''

	def __init__(self, app, fn):
		self._app = app
		self._func = fn
		self._has_request_arg = has_request_arg(fn)
		self._has_var_kw_arg = has_var_kw_arg(fn)
		self._has_named_kw_args = has_named_kw_args(fn)
		self._named_kw_args = get_named_kw_args(fn)
		self._required_kw_args = get_required_kw_args(fn)
	
	# 1.定义kw，用于保存参数
	# 2.判断视图函数是否存在关键词参数，如果存在根据POST或者GET方法将request请求内容保存到kw
	# 3.如果kw为空（说明request无请求内容），则将match_info列表里的资源映射给kw；若不为空，把命名关键词参数内容给kw
	# 4.完善_has_request_arg和_required_kw_args属性
	async def __call__(self, request):  # __call__这里要构造协程
		kw = None  # 定义kw，用于保存request中参数
		if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
			# 若视图函数有命名关键词或关键词参数
			if request.method == 'POST':  #判断客户端发来的方法是否为POST
				# 根据request参数中的content_type使用不同解析方法：
				if not request.content_type:  # 如果content_type不存在，返回400错误
					return web.HTTPBadRequest(text='Missing content-Type.')
				ct = request.content_type.lower()  # 小写，便于检查
				if ct.startswith('application/json'):  # json格式数据
					params = await request.json()  # 仅解析body字段的json数据
					if not isinstance(params, dict):  # request.json()返回dict对象
						return web.HTTPBadRequest(text='Json body must be object.')
					kw = params
				# form表单请求的编码方式
				elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
					params = await request.post()  #返回post的内容中解析后的数据，dict-like对象
					kw = dict(**params)  # 组成dict，统一kw格式
				else:
					return web.HTTPBadRequest(text='Unsupported content-Type: %s' % request.content_type)
			if request.method == 'GET':
				qs = request.query_string  # 返回URL查询语句，？后的键值，string形式
				if qs:
					kw = dict()
					'''
					解析url中?后面的键值对的内容
					qs = 'first=f,s&second=s'
					parse.parse_qs(qs, True).items()
					>>> dict([('first', ['f,s']), ('second', ['s'])])
					'''
					for k, v in parse.parse_qs(qs, True).items():  # 返回查询变量和值的映射，dict对象，True表示不忽略空格
						kw[k] = v[0]
		if kw is None:  # 若request中无参数
			# request.match_info返回dict对象。可变路由中的可变字段{variable}为参数名，传入request请求的path为值
			# 若存在可变路由：/a/{name}/c，可匹配path为：/a/jack/c的request
			# 则reqwuest.match_info返回{name = jack}
			kw = dict(**request.match_info)
		else:  # request有参数
			if not self._has_var_kw_arg and self._named_kw_args:  # 若视图函数只有命名关键词参数没有关键词参数
				copy = dict()
				for name in self._named_kw_args:  # 只保留命名关键词参数
					if name in kw:
						copy[name] = kw[name]
				kw = copy  # kw中只存在命名关键词参数
			for k, v in request.match_info.items():  # 将request.match_info中的参数传入kw
				if k in kw:  # 检查kw中的参数是否和match_info中的重复
					logging.warning('Duplicate arg name in named arg and kw args:%s' % k)
				kw[k] = v
		if self._has_request_arg:  #视图函数中存在request参数
			kw['request'] = request
		if self._required_kw_args:  # 视图函数存在无默认值的命名关键词参数
			for name in self._required_kw_args:
				if not name in kw:  # 若未传入必须参数名，报错。
					return web.HTTPBadRequest(text='Missing argument: %s' % name)
		# 至此，kw为视图函数fn真正能调用的参数，request请求中的参数，终于传递给了视图函数
		logging.info('call with args: %s' % str(kw))
		try:
			r = await self._func(**kw)
			return r
		except APIError as e:
			return dict(error=e.error, data=e.data, message=e.message)


# 添加静态文件，如image，css，javascript等
def add_static(app):
	# 拼接static文件目录
	path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
	app.router.add_static('/static/', path)
	logging.info('add static %s => %s' % ('/static/', path))


# add_route函数功能：
# 1、验证视图函数是否拥有method和path参数
# 2、将视图函数转变为协程
def add_route(app, fn):
	method = getattr(fn, '__method__', None)
	path = getattr(fn, '__route__', None)
	if path is None or method is None:
		raise ValueError('@get or @post not defined in %s.' % str(fn))
	# 判断URL处理函数是否协程并且是生成器
	if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
		fn = asyncio.coroutine(fn)  # 将fn转变成协程
	logging.info('add route %s %s ==> %s(%s)' % (method, path, fn.__name__, ','.join(inspect.signature(fn).parameters.keys())))
	# 在app中注册经RequestHandler类封装的视图函数
	app.router.add_route(method, path, RequestHandler(app, fn))


def add_routes(app, module_name):
	'''
	返回'.'最后出现的位置
    如果为-1，说明是 module_name中不带'.',例如(只是举个例子) handles 、 models
    如果不为-1,说明 module_name中带'.',例如(只是举个例子) aiohttp.web 、 urlib.parse()    n分别为 7 和 5
    我们在app中调用的时候传入的module_name为handles,不含'.',if成立, 动态加载module
	'''
	n = module_name.rfind('.')
	if n == (-1):  # n=-1,说明module_name中不含’.‘,动态加载该module
		# __import__作用通import语句，但__import__是一个函数，并且只接收字符串作为参数
		# __import__('os',globals(),locals(),['path','pip'], 0) ,等价于from os import path, pip
		mod = __import__(module_name, globals(), locals())
	else:
		'''
		n!=-1,说明module_name中含'.'
		比如 aaa.bbb 类型,我们需要从aaa中加载bbb
        n = 3
        name = module_name[n+1:] 为bbb
        module_name[:n] 为aaa
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)，动态加载aaa.bbb
        上边三句其实相当于：
            aaa = __import__(module_name[:n], globals(), locals(), ['bbb'])
            mod = aaa.bbb
        还不明白的话看官方文档,讲的特别清楚：
            https://docs.python.org/3/library/functions.html?highlight=__import__#__import__
		'''
		name = module_name[n+1:]
		mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
	for attr in dir(mod):  # for循环把所有的url处理函数给注册了，dir()迭代出mod模块中所有的类，实例及函数等对象,str形式
		if attr.startswith('_'):
			continue  # 忽略'_'开头的对象，直接继续for循环
		fn = getattr(mod, attr)
		# 确保是函数
		if callable(fn):
			# 确保视图函数存在method和path
			method = getattr(fn, '__method__', None)
			path = getattr(fn, '__route__', None)
			if method and path:  # 注册url处理函数fn，如果不是url处理函数,那么其method或者route为none，自然也不会被注册
				add_route(app, fn)