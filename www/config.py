# !/usr/bin/python3
# -*- coding: utf-8 -*-
# @Time    : 2018/6/25 13:38
# @Author  : zzj
# @Email   : XX@XX.com
# @File    : config.py
# @Software: PyCharm


import config_default
# 这个类主要可以使dict对象，以object.key 形式来替代  object[key]来取值


class Dict(dict):
	
	def __init__(self, names=(), values=(), **kw):
		super(Dict, self).__init__(**kw)
		# zip函数将参数数据分组返回[(arg1[0],arg2[0],arg3[0]...),(arg1[1],arg2[1],arg3[1]...),,,]
		# 以参数中元素数量最少的集合长度为返回列表长度
		for k, v in zip(names, values):
			self[k] = v
	
	def __getattr__(self, key):
		try:
			return self[key]
		except KeyError:
			raise AttributeError(r"'Dict' object has no attribute '%s'" % key)
	
	def __setattr__(self, key, value):
		self[key] = value


# 用override的已存在配置覆盖default里配置
# 简单地递归


def merge(defaults, override):
	r = {}
	for k, v in defaults.items():
		if k in override:
			if isinstance(v, dict):
				r[k] = merge(v, override[k])
			else:
				r[k] = override[k]
		else:
			r[k] = v
	return r

def toDict(d):
	# 把配置文件转换为Dict类实例
	D = Dict()
	for k, v in d.items()
		D[k] = toDict(v) if isinstance(v, dict) else v
	return D


configs = config_default.configs  # configs默认为默认配置

try:
	import config_override
	# 这里把自定义配置文件里的配置项覆盖了默认配置里的配置项，
	# 如果自定义配置里没有定义，默认配置定义了，则还是沿用默认配置
	configs = merge(configs, config_override.configs)
except ImportError:
	pass

configs = toDict(configs)