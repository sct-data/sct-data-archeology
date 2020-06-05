#!/usr/bin/env python
# -*- coding: utf-8
# Retrieve URLs from a blob

import sys, io, os
import logging
import re
import json
import ast

logger = logging.getLogger()

data = sys.stdin.read()

try:
	tree = ast.parse(data, mode="exec")
except SyntaxError:
	raise SystemExit(1)

def find_dicts(node):
	ret = list()

	if isinstance(node, ast.Dict):#tp.__name__ == "Dict":
		if 0:
			print(dir(node))
			print(node)
			print(node._attributes)
			print(node._fields)
			print(node.keys)
			print(node.values)

		d = dict()
		good = True
		for k, v in zip(node.keys, node.values):
			if not isinstance(k, ast.Str):
				logger.warning("Discarding by key: %s", k)
				good = False
				continue

			d[k.s] = list()

			if isinstance(v, (ast.List, ast.Tuple)):
				for elt in v.elts:
					#print(elt)
					if not isinstance(elt, ast.Str):
						logger.warning("Bad %s", elt)
						print(elt)
						good = False
						continue

					d[k.s].append(elt.s)
			elif isinstance(v, ast.Str):
				d[k.s].append(v.s)

		if good:
			ret.append(d)

	for x in ast.iter_child_nodes(node):
		ret += find_dicts(x)

	return ret

def find_urls(node):
	ret = list()

	if isinstance(node, ast.Str):
		m = re.match(r"^https?://.*$", node.s)
		if m is not None:
			ret.append(node.s)

	for x in ast.iter_child_nodes(node):
		ret += find_urls(x)

	return ret


urls = set(find_urls(tree)).difference(["https://"])

dicts = find_dicts(tree)

if len(dicts) != 1:
	raise NotImplementedError("Got many dicts: {}".format(dicts))

d = dicts[0]

dict_urls = set()
for k, vals in d.items():
	for v in vals:
		dict_urls.add(v)

diff = urls.difference(dict_urls)

if diff:
	raise NotImplementedError("Stale URLs: {}".format(diff))

print(json.dumps(d))
