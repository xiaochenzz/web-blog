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
def create_args_string(num):  # 在ModelMetaclass的特殊变量中用到
	# insert插入属性时候，增加num个数量的占位符'?'
	L = []
	for n in range(num):
		L.append('?')
	return ', '.join(L)



# ===============================属性类===================================
class Field(object):  # 属性的基类，给其它具体Model类继承

	def __init__(self, name, column_type, primary_key, default):
		self.name = name
		self.column_type = column_type
		self.primary_key = primary_key
		self.default = default   # 如果存在default，在getValueOrDefault中会被用到

	def __str__(self):  # 直接print的时候定制输出信息为类名和列类型和列名
		return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)


class StringField(Field):

	def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):   # String一般不作为主键，所以默认False,DDL是数据定义语言，为了配合mysql，所以默认设定为100的长度
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
		super().__init__(name, 'text', False, default)  # 这个是不能作为主键的对象，所以这里直接就设定成False了


class ModelMetaclass(type):
	# 该元类主要使得Model基类具备以下功能:
	# 1.任何继承自Model的类（比如User），会自动通过ModelMetaclass扫描映射关系
	# 并存储到自身的类属性如__table__、__mappings__中
	# 2.创建了一些默认的SQL语句

	def __new__(cls, name, bases, attrs):
		if name == 'Model':  # 排除Model这个基类
			return type.__new__(cls, name, bases, attrs)
		tableName = attrs.get('__table__', None) or name  # 获取table名称，一般就是Model类的类名，前面get失败了直接赋值name
		logging.info('  found model: %s (table: %s)' % (name, tableName))
		# 获取所有的Field和主键名
		mappings = dict()   # 保存属性和值的k，v
		fields = []         # 保存Model类的属性
		primaryKey = None   # 保存Model类的主键
		for k, v in attrs.items():
			if isinstance(v, Field):   # 如果是Field类型的则加入mappings对象
				logging.info('found mapping : %s ==> %s' % (k, v))
				mappings[k] = v
				# k，v键值对全部保存到mappings中，包括主键和非主键
				if v.primary_key:  # 如果v是主键即primary_key=True，尝试把其赋值给primaryKey属性
					if primaryKey: # 如果primarykey属性已经不为空了，说明已经有主键了，则抛出错误，因为只能1个主键
						raise StandardError('Duplicate primary key for field: %s' % k)
					primaryKey = k  # 如果主键还没被赋值过，则直接赋值
				else:  # v不是主键，即primary_key=False的情况
					fields.append(k)  # 非主键全部放到fields列表中
		if not primaryKey:  # 如果遍历完还没找到主键，则抛出错误
			raise StandardError('Primary key not found...')
		for k in mappings.keys():  # 清除mappings，防止实例属性覆盖类的同名属性，造成运行时错误
			# attrs中对应的属性则需要删除。作者指的是attrs的属性和mappings中的属性发生冲突，具体原因可能需要自己实际体验下这个错误才知道
			attrs.pop(k)
		# %s占位符全部替换成具体的属性名
		escaped_fields = list(map(lambda f: '`%s`' % f, fields))
		# =============初始化私有的特别属性=====
		attrs['__mappings__'] = mappings  # 保存属性和列的映射关系，赋值给特殊类变量__mappings__
		attrs['__table__'] = tableName
		attrs['__primary_key__'] = primaryKey  # 主键属性名
		attrs['__fields__'] = fields  # 除主键外的属性名
		
		# ===========构造默认的select,insert,update,delete语句=======
		# 这里据说不用`，在mysql里面会报错，待验证
		#  默认的select语句貌似没怎么被用到，我感觉通用性如果不好，还不如不加吧。后面就findAll方法用到了
		# insert语句前面有3个占位符，所以从第四个%开始应该是(用于替换第一个%的值a1，替换第二个%的值a2，替换第三个%的值a3)
		# 默认想执行的应该是update tableName set 属性1=？，属性2=？，... where 主键=primray_key
		# a1是tableName没问题，a2应该是主键的属性，a3则通过匿名函数结合map将%s=?全部替换成属性名=？
		# 因此这里的匿名函数就是讲%s这个占位符替换成`属性名`=?
		# 占位符有很多问号，为了方便就直接使用了create_ars_string函数来生成num个占位符的string
		attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
		attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
		attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
		attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
		return type.__new__(cls, name, bases, attrs)


class Model(dict, metaclass=ModelMetaclass):
	
	# 继承dict是为了使用方便，例如对象实例user['id']即可轻松通过UserModel去数据库获取到id
	# 元类自然是为了封装我们之前写的具体的SQL处理函数，从数据库获取数据
	def __init__(self, **kw):
		# 调用dict的父类__init__方法用于创建Model,super(类名，类对象)
		super(Model, self).__init__(**kw)

	def __getattr__(self, key):
		# 调用不存在的属性时返回一些内容
		try:
			return self[key]  # 如果存在则正常返回
		except KeyError:
			raise AttributeError(r"'Model' object has no attribute '%s'" % key)

	def __setattr__(self, key, value):
		# 设定Model里面的key-value对象，这里value允许为None
		self[key] = value

	def getValue(self, key):
		# 获取某个具体的值，肯定存在的情况下使用该函数,否则会使用__getattr()__
		# 获取实例的key，None是默认值
		return getattr(self, key, None)

	def getValueOrDefault(self, key):
		# 这个方法当value为None的时候能够返回默认值
		value = getattr(self, key, None)
		if value is None:  # 不存在这样的值则直接返回
			field = self.__mappings__[key]
			if field.default is not None:  # 如果实例的域存在默认值，则使用默认值
				# field.default是callable的话则直接调用
				value = field.default() if callable(field.default) else field.default
				logging.debug('using default value for %s: %s' % (key, str(value)))
				setattr(self, key, value)
		return value
	
	# -------------每个Model类的子类实例应该具备的执行SQL的方法比如save------
	@classmethod  #类方法
	async def findAll(cls, where=None, args=None, **kw):
		sql = [cls.__select__]  # 获取默认的select语句
		if where:   # 如果有where语句，则修改sql语句
			sql.append('where')  # sql里面加上where关键字
			sql.append(where)  # 这里的where实际上是colName=‘xxx’这样的条件表达式
		if args is None:
			args = []
		orderBy = kw.get('orderBy', None)  # 从kw中查看是否有orderby属性
		if orderBy:
			sql.append('order by')
			sql.append(orderBy)
		limit = kw.get('limit', None)  # mysql中可以使用limit关键字
		if limit is not None:
			sql.append('limit')
			if isinstance(limit, int):  # 如果是int类型则增加占位符
				sql.append('?')
				args.append(limit)
			elif isinstance(limit, tuple) and len(limit) == 2:  # limit可以取2个参数，表示一个范围
				sql.append('?, ?')
				args.extend(limit)
			else:  # 其他情况自然是语法问题
				raise ValueError('Invalid limit value: %s' %  str(limit))
		# 在原来默认sql语句后面再添加语句，要加个空格
		rs = await select(' '.join(sql), args)
		return [cls(**r) for r in rs]  # 返回结果，结果是list对象，里面的元素是dict类型的


	@classmethod
	async def findNumber(cls, selectField, where=None, args=None):
		# 获取行数
		sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
		if where:
			sql.append('where')
			sql.append(where)
		rs = await select(' '.join(sql), args, 1)  # size=1
		if len(rs) == 0:
			return None
		return rs[0]['_num_']  # 有结果则rs这个list中第一个词典元素_num_这个key的value值

	@classmethod
	async def find(cls, pk):
		# 根据主键查找
		#pk是dict对象
		rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
		if len(rs) == 0:
			return None
		return cls(**rs[0])

	async def save(self):
		# arg是保存所有Model实例属性和主键的list,使用getValueOrDefault方法的好处是保存默认值
		# 将自己的fields保存进去
		args = list(map(self.getValueOrDefault, self.__fields__))
		args.append(self.getValueOrDefault(self.__primary_key__))
		rows = await execute(self.__insert__, args)  # 使用默认插入函数
		if rows != 1:  # 插入失败就是row！=1
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