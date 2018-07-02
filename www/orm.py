#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @Time    : 2018/6/8 23:36
# @Author  : zzj
# @Email   : zhongjv@163.com
# @File    : orm.py
# @Software: PyCharm


import asyncio
import logging
import aiomysql


def log(sql, args=()):
	# 用于打印执行的sql语句
	logging.info('SQL: %s' % sql)


async def create_pool(loop, **kw):
	logging.info('create database connection pool...')
	# 该函数用于创建连接池
	global __pool  # 全局变量用于保存连接池
	__pool = await aiomysql.create_pool(
		host=kw.get('host', 'localhost'),  # 默认定义host名字为localhost
		port=kw.get('port', 3306),   # 默认定义mysql的默认端口为3306
		user=kw['user'],   # user是通过关键字参数传进来的
		password=kw['password'],  # 密码也是通过关键字参数传进来的
		db=kw['db'],  # 数据库名称
		charset=kw.get('charset', 'utf8'),   # 默认数据库字符集是utf-8
		autocommit=kw.get('autocommit', True),  # 默认自动提交事务
		maxsize=kw.get('maxsize', 10),  # 连接池最多同时处理10个请求
		minsize=kw.get('minsize', 1),  # 李娜劫持最少1个请求
		loop=loop   # 传递信息循环对象loop用于异步执行
	)


# =============================SQL处理函数区======================================
# select和execute方法是实现其他Model类中SQL语句都经常要用的方法，原本是全局函数，这里作为静态函数处理

async def select(sql, args, size=None):
	# select语句则对应select方法，传入sql语句和参数
	log(sql, args)
	global __pool
	async with __pool.get() as conn:   # 异步等待连接池对象返回可以连接线程，with语句则封装了清理（关闭conn）及处理异常的工作
		async with conn.cursor(aiomysql.DictCursor) as cur:   #等待连接对象返回DictCursor，可以通过dict的方式获取数据库对象，需要通过游标对象执行SQL
			await cur.execute(sql.replace('?', '%s'), args or ())  # 所有args都通过replace方法把占位符替换成%，args是execute方法的参数
			if size:   # 如果指定要返回几行
				rs = await cur.fetchmany(size)  # 从数据库获取指定的行数
			else:  # 如果没指定返回几行，即size=None
				rs = await cur.fetchall()  # 都要异步执行
		logging.info('rows returned: %s' % len(rs))  # 输出LOG信息
		return rs   # 返回结果集


async def execute(sql, args, autocommit=True):  # execute方法志返回结果数，不返回结果集，用于insert，update这些sql语句
	log(sql)
	async with __pool.get() as conn:
		if not autocommit:
			await conn.begin()
		try:
			async with conn.cursor(aiomysql.DictCursor) as cur:
				await cur.execute(sql.replace('?', '%s'), args)  # 执行sql语句，同时替换占位符
				affected = cur.rowcount   # 返回受影响的行数
			if not autocommit:
				await conn.commit()
		except BaseException as e:
			if not autocommit:
				await conn.rollback()
			raise
		return affected


# ===============================Model基类以及元类================================
# 对象和关系之间要映射起来，首先考虑创建所有Model类的一个父类，具体的Model对象（就是数据库表在你代码中对应的对象）再继承这个基类
def create_args_string(num):
	L = []
	for n in range(num):
		L.append('?')
	return ', '.join(L)


class Field(object):

	def __init__(self, name, column_type, primary_key, default):
		self.name = name
		self.column_type = column_type
		self.primary_key = primary_key
		self.default = default

	def __str__(self):
		return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)


class StringField(Field):

	def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
		super().__init__(name, ddl, primary_key, default)


class BooleanField(Field):

	def __init__(self, name=None, default=False):
		super().__init__(name, 'boolean', False, default)


class IntegerField(Field):

	def __init__(self, name=None, primary_key=False, default=0):
		super().__init__(name, 'bigint', primary_key, default)


class FloatField(Field):

	def __init__(self, name=None, primary_key=False, default=0.0):
		super().__init__(name, 'real', primary_key, default)


class TextField(Field):

	def __init__(self, name=None, default=None):
		super().__init__(name, 'text', False, default)


class ModelMetaclass(type):

	def __new__(cls, name, bases, attrs):
		if name == 'Model':
			return type.__new__(cls, name, bases, attrs)
		tableName = attrs.get('__table__', None) or name
		logging.info('  found model: %s (table: %s)' % (name, tableName))
		mappings = dict()
		fields = []
		primaryKey = None
		for k, v in attrs.items():
			if isinstance(v, Field):
				logging.info('found mapping : %s ==> %s' % (k, v))
				mappings[k] = v
				if v.primary_key:
					if primaryKey:
						raise StandardError('Duplicate primary key for field: %s' % k)
					primaryKey = k
				else:
					fields.append(k)
		if not primaryKey:
			raise StandardError('Primary key not found...')
		for k in mappings.keys():
			attrs.pop(k)
		escaped_fields = list(map(lambda f: '`%s`' % f, fields))
		attrs['__mappings__'] = mappings  # 保存属性和列的映射关系
		attrs['__table__'] = tableName
		attrs['__primary_key__'] = primaryKey  # 主键属性名
		attrs['__fields__'] = fields  # 除主键外的属性名
		attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
		attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
		attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
		attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
		return type.__new__(cls, name, bases, attrs)


class Model(dict, metaclass=ModelMetaclass):

	def __init__(self, **kw):
		super(Model, self).__init__(**kw)

	def __getattr__(self, key):
		try:
			return self[key]
		except KeyError:
			raise AttributeError(r"'Model' object has no attribute '%s'" % key)

	def __setattr__(self, key, value):
		self[key] = value

	def getValue(self, key):
		return getattr(self, key, None)

	def getValueOrDefault(self, key):
		value = getattr(self, key, None)
		if value is None:
			field = self.__mappings__[key]
			if field.default is not None:
				value = field.default() if callable(field.default) else field.default
				logging.debug('using default value for %s: %s' % (key, str(value)))
				setattr(self, key, value)
		return value

	@classmethod
	async def findAll(cls, where=None, args=None, **kw):
		sql = [cls.__select__]
		if where:
			sql.append('where')
			sql.append(where)
		if args is None:
			args = []
		orderBy = kw.get('orderBy', None)
		if orderBy:
			sql.append('order by')
			sql.append(orderBy)
		limit = kw.get('limit', None)
		if limit is not None:
			sql.append('limit')
			if isinstance(limit, int):
				sql.append('?')
				args.append(limit)
			elif isinstance(limit, tuple) and len(limit) == 2:
				sql.append('?, ?')
				args.extend(limit)
			else:
				raise ValueError('Invalid limit value: %s' %  str(limit))
		rs = await select(' '.join(sql), args)
		return [cls(**r) for r in rs]

	@classmethod
	async def findNumber(cls, selectField, where=None, args=None):
		sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
		if where:
			sql.append('where')
			sql.append(where)
		rs = await select(' '.join(sql), args, 1)
		if len(rs) == 0:
			return None
		return rs[0]['_num_']

	@classmethod
	async def find(cls, pk):
		rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
		if len(rs) == 0:
			return None
		return cls(**rs[0])

	async def save(self):
		args = list(map(self.getValueOrDefault, self.__fields__))
		args.append(self.getValueOrDefault(self.__primary_key__))
		rows = await execute(self.__insert__, args)
		if rows != 1:
			logging.warn('failed to insert record: affected rows: %s' % rows)

	async def update(self):
		args = list(map(self.getValue, self.__fields__))
		args.append(self.getValue(self.__primary_key__))
		rows = await execute(self.__update__, args)
		if rows != 1:
			logging.warn('failed to update by primary key: affected rows: %s' % rows)

	async def remove(self):
		args = [self.getValue(self.__primary_key__)]
		rows = await execute(self.__delete__, args)
		if rows != 1:
			logging.warn('failed to remove by primary key: affected rows: %s' % rows)