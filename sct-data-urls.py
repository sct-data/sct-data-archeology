#!/usr/bin/env python
# -*- coding: utf-8
# Retrieve URLs from SCT source code

import sys, io, os
import logging
import re, json
import datetime
import ast
import multiprocessing
import subprocess
import urllib.request
import hashlib

import pygit2

import rfc6266 # HTTP Content-Disposition Header Field use
# Note: cgi.parse_header is not perfect for this
# Note: remove the "add_handler" from rfc6266 if crashes

logger = logging.getLogger()


def get_blob_urls(data) -> bytes:
	for interpreter in (["python3"], ["python2"]):
		cmd = interpreter + ["sct-data-urls-find-urlmap-in-blob.py"]

		proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

		out, err = proc.communicate(data)

		err = err.decode("utf-8")
		ret = proc.poll()

		if ret == 1:
			logger.warning("Err: %s", err)
			continue

		if ret != 0:
			logger.exception("Unexpected parsing issue: %s", err)
			continue

		return out

	raise ValueError()

def walk_tree(path):
	for obj in path[-1]:
		if obj.type_str == "tree":
			yield from walk_tree(path + [obj])
		else:
			yield path, obj

def download(src, dst):

	do_download = True
	if os.path.exists(dst):

		logger.info("- %s: local file exists (%s)", src, dst)

		do_download = False

		"""
		import xdg.Mime

		path = dst

		try:
			filemime = xdg.Mime.get_type2(path)
		except AttributeError:
			filemime = xdg.Mime.get_type(path)

		filetype = str(filemime)
		logger.info(" file type: %s", filetype)

		if filetype == "application/gzip":
			cmd = ["gunzip", "--stdout", dst]
			proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL)
			res = proc.wait()
			if res == 0:
				do_download = False

		elif filetype == "application/zip":
			import zipfile
			try:
				z = zipfile.ZipFile(dst)
				l = z.infolist()
				do_download = False
			except Exception as e:
				logger.exception("NG zip file: %s->%s (%s)", src, dst, e)
				pass
		else:
			logger.error(" Unsupported file type: %s", filetype)
		"""

	if do_download:
		logger.debug("Downloading %s", src)
		try:
			x, headers = urllib.request.urlretrieve(src, dst + ".tmp")

			filename = None
			if "Content-Disposition" in headers:
				disp = headers["Content-Disposition"]
				filename = rfc6266.parse_headers(disp, relaxed=True).filename_unsafe
				if filename is not None:
					filename = os.path.basename(filename)

			if filename is None:
				filename = os.path.basename(src)

			with io.open(dst + ".filename", "w", encoding="utf-8") as fo:
				fo.write(filename)

			os.rename(dst + ".tmp", dst)

			logger.debug("Downloaded %s", filename)
			#logger.debug("Headers: %s", headers)
		except Exception as e:
			logger.exception("NG download: %s", src)


def main():

	import argparse

	parser = argparse.ArgumentParser(
	 description="Mesklean HTTP API smoke test",
	)

	parser.add_argument("--log-level",
	 default="INFO",
	 help="Logging level (eg. INFO, see Python logging docs)",
	)

	try:
		import argcomplete
		argcomplete.autocomplete(parser)
	except:
		pass

	args = parser.parse_args()

	logging.root.setLevel(getattr(logging, args.log_level))

	logging.basicConfig(
	)


	repo = pygit2.Repository("spinalcordtoolbox")

	last = repo[repo.head.target]

	if 0:
		logger.info("Collecting URLs")

		for commit in repo.walk(last.id, pygit2.GIT_SORT_TIME):
			logger.debug("- %s", commit.id)

			for path, blob in walk_tree([commit.tree]):
				path = "/".join(tree.name for tree in path[1:]) + "/" + blob.name

				if not path.endswith(".py"):
					continue

				if not blob.name == "sct_download_data.py":
					continue

				url_file = os.path.join("tmp-sct-data-urls/blob-urls", str(blob.id))
				if os.path.exists(url_file):
					continue

				logger.debug("  - %s: getting URLs")

				try:
					urls = get_blob_urls(blob.data)
				except ValueError:
					logger.info("Couldn't get URLs in %s", blob.id)
					urls = b""

				with io.open(url_file, "wb") as fo:
					fo.write(urls)

	if 0:
		# oops
		key_list_path = os.path.join("tmp-sct-data-urls", "keys.yaml")
		if os.path.exists(key_list_path):
			with io.open(key_list_path, "rb") as fi:
				all_keys = set(yaml.safe_load(fi))

	logger.info("Gathering keys & URLs")

	all_keys = set()
	all_urls = set()
	for commit in repo.walk(last.id, pygit2.GIT_SORT_TIME):
		for path, blob in walk_tree([commit.tree]):
			url_file = os.path.join("tmp-sct-data-urls/blob-urls", str(blob.id))
			if not os.path.exists(url_file):
				continue

			with io.open(url_file, "rb") as fi:
				urls = fi.read()
				if not urls:
					continue
				d = json.loads(urls.decode("utf-8"))
				for k, urls in d.items():
					all_keys.add(k)
					all_urls.update(urls)

	logger.info("There are %d keys", len(all_keys))

	if 0:
		logger.info("Downloading %d URLs", len(all_urls))

		jobs = list()
		pool = multiprocessing.Pool()
		for url in all_urls:
			h = hashlib.sha3_512()
			h.update(url.encode())
			dst = os.path.join("tmp-sct-data-urls/data", h.hexdigest())
			job = pool.apply_async(download, (url, dst))
			jobs.append(job)
		for job in jobs:
			job.get()


	for idx_key, key in enumerate(sorted(all_keys)):
		#if idx_key+1 < 12:
		#	continue

		key_hist_path = os.path.join("tmp-sct-data-urls", key + ".yml")
		if os.path.exists(key_hist_path) and os.path.getsize(key_hist_path) > 3:
			continue

		logger.info("- %d/%d %s", idx_key+1, len(all_keys), key)

		# Walk all revs and find when URL changed

		commit_and_urls = list()

		last_commit_and_urls = None

		walker = repo.walk(last.id, pygit2.GIT_SORT_TOPOLOGICAL)
		walker.simplify_first_parent()

		for commit in walker:
			#logger.debug(" - %s", commit.commit_time)

			gotit_in_path = None

			for path, blob in walk_tree([commit.tree]):

				path = "/".join(tree.name for tree in path[1:]) + "/" + blob.name

				url_file = os.path.join("tmp-sct-data-urls/blob-urls", str(blob.id))
				if not os.path.exists(url_file):
					continue

				with io.open(url_file, "rb") as fi:
					urls = fi.read()
					if not urls:
						continue
					d = json.loads(urls.decode("utf-8"))
					if key in d:
						if gotit_in_path is not None:
							logger.warning("Already got URLs in %s", gotit_in_path)

						cur_urls = set(d[key])
						logger.info("- %s", cur_urls)
						if last_commit_and_urls is not None:
							if not cur_urls.intersection(last_commit_and_urls[1]):
								commit_and_urls.append(last_commit_and_urls)
						last_commit_and_urls = commit, cur_urls
						gotit_in_path = path

		if last_commit_and_urls is not None:
			if len(commit_and_urls) == 0 or commit_and_urls[-1] != last_commit_and_urls:
				commit_and_urls.append(last_commit_and_urls)

		if commit_and_urls is None:
			logger.warning("No URLs for %s", key)
			continue

		root = list()

		for commit, urls in reversed(commit_and_urls):
			commit_time = datetime.datetime.utcfromtimestamp(commit.commit_time)
			entry = dict()
			entry.update(
			 urls=sorted(urls),
			 commit=dict(
			  id=str(commit.id),
			  author_name=commit.author.name,
			  author_email=commit.author.email,
			  author_time=datetime.datetime.utcfromtimestamp(commit.author.time).strftime("%Y-%m-%dT%H:%M:%SZ"),
			  commit_time=commit_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
			  message=commit.message,
			 ),
			 #filename=archive_filename,
			)
			logger.info(" - %s %s", commit.id, urls)
			root.append(entry)

		with io.open(key_hist_path, "w", encoding="utf-8") as fo:
			import yaml
			yaml.dump(root, fo)

if __name__ == "__main__":
	res = main()
	raise SystemExit()
