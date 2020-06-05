#!/usr/bin/env python
# -*- coding: utf-8
# Convert zip bundles with metadata into git repositories

import sys, io, os
import logging
import re, json
import datetime
import ast
import multiprocessing
import subprocess
import urllib.request
import urllib.error
import hashlib

import pygit2
import yaml
import xdg.Mime


logger = logging.getLogger()

BAD_URLS = (
 "https://osf.io/u79sr/?pid=6zbyf/?action=download",
)

GH_TOKEN = os.environ["GH_TOKEN"].strip()


def archive_to_tree(repo, urls):
	"""
	Build a pygit2 treeish object from an archive
	:return: downloaded archive path, treeish, archive's most recent mtime
	"""
	t_max = 0

	# Get local file + ensure URLs have same data

	digests = set()

	for url in urls:

		if url in BAD_URLS:
			continue

		h = hashlib.sha3_512()
		h.update(url.encode())
		dst = os.path.join("tmp-sct-data-urls", "data", h.hexdigest())

		if os.path.exists(dst):
			h = hashlib.sha3_512()
			with io.open(dst, "rb") as fi:
				h.update(fi.read())
			digests.add(h.digest())
			logger.debug("%s -> %s size=%d h=%s", url, dst, os.path.getsize(dst), h.hexdigest())

	if len(digests) == 0:
		logger.warning("No data for %s", urls)
		return

	if len(digests) > 1:
		logger.error("Inconsistent data in URLS %s", urls)
		return

	path = archive_path = dst
	logger.info(" Using %s", path)

	try:
		filemime = xdg.Mime.get_type2(path)
	except AttributeError:
		filemime = xdg.Mime.get_type(path)

	filetype = str(filemime)


	logger.debug("Filetype: %s", filetype)

	trees = {"": repo.TreeBuilder()}

	if filetype == "application/zip":
		import zipfile
		z = zipfile.ZipFile(dst)

		for info in z.infolist():
			if "__MACOSX" in info.filename:
				continue
			if "/._" in info.filename:
				continue
			if "/.DS_Store" in info.filename:
				continue

			tY, tm, td, tH, tM, tS = info.date_time
			t = datetime.datetime(year=tY, month=tm, day=td,
			 hour=tH, minute=tM, second=tS,
			 tzinfo=datetime.timezone.utc)
			if t.timestamp() > t_max:
				t_max = t.timestamp()

			if "/" in path:
				dirname, basename = info.filename.rsplit("/", 1)
			else:
				dirname, basename = "", info.filename

			if basename == "":
				logger.debug("  - tree %s", info.filename)
				tree = repo.TreeBuilder()
				trees[info.filename[:-1]] = tree
			else:
				tree = trees[dirname]
				logger.debug("  - blob %s", info.filename)
				data = z.read(info.filename)
				blob_id = repo.create_blob(data)
				tree.insert(basename, blob_id, pygit2.GIT_FILEMODE_BLOB)

	elif filetype == "application/gzip":
		import gzip
		z = gzip.open(dst)
		import tarfile
		tar = tarfile.open(fileobj=z)
		while True:
			ti = tar.next()

			if ti is None:
				break

			if ti.mtime > t_max:
				t_max = ti.mtime

			path = ti.name

			if path == ".":
				continue

			if "__MACOSX" in path:
				continue
			if "/._" in path:
				continue
			if "/.DS_Store" in path:
				continue

			if "/" in path:
				dirname, basename = path.rsplit("/", 1)
			else:
				dirname, basename = "", path

			if dirname == ".":
				dirname = ""

			if ti.isdir():
				logger.debug("  - tree %s", path)
				tree = repo.TreeBuilder()
				trees[path] = tree
			else:
				tree = trees[dirname]
				logger.debug("  - blob %s", path)
				fi = tar.extractfile(ti)
				data = fi.read()
				blob_id = repo.create_blob(data)
				tree.insert(basename, blob_id, pygit2.GIT_FILEMODE_BLOB)
	else:
		raise NotImplementedError(filetype)

	# TODO create intermediate trees if needed

	if 0:
		if do_download and (src.endswith(".gz") or "osf.io" in src):
			cmd = ["gunzip", "--stdout", dst]
			proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL)
			res = proc.wait()

	# Get tree from trees
	done = set()
	todo = set(trees.keys())

	logger.debug("Trees: %s", todo)

	while todo:
		logger.debug("- todo: %s", sorted(todo))
		logger.debug("- done: %s", sorted(done))

		for path, builder in trees.items():

			if path in done:
				continue

			# Check for kids todo
			for subpath, subbuilder in trees.items():
				if subpath == path:
					continue
				if subpath in done:
					continue
				if path == "" or subpath.startswith(path + "/"):
					break
			else:
				logger.debug(" - %s: no kids", path)

				if path == "":
					logger.debug(" (root)")
					builder.write()
					done.add(path)
					todo = set()
					continue

				if "/" in path:
					dirname, basename = path.rsplit("/", 1)
				else:
					dirname, basename = "", path

				logger.debug(" - %s: no kids, add to parent %s and write", path, dirname)

				parentbuilder = trees[dirname]
				parentbuilder.insert(basename, builder.write(), pygit2.GIT_FILEMODE_TREE)
				done.add(path)
				todo = todo.difference(done)

	basename = os.path.basename(os.path.dirname(os.path.dirname(repo.path)))
	if basename in trees:
		path = basename
	elif basename + "-master" in trees:
		# Saw some files in -master/ (github zip export?)
		# -> Work that around.
		path = basename + "-master"
	else:
		path = ""

	logger.debug("Returning tree at %s for %s (%s)", path, repo.path, basename)

	builder = trees[path]

	return archive_path, builder.write(), t_max



def main():

	import argparse

	parser = argparse.ArgumentParser(
	 description="Convert bundles to git history",
	)

	parser.add_argument("--log-level",
	 default="INFO",
	 help="Logging level (eg. INFO, see Python logging docs)",
	)

	parser.add_argument("config",
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

	dirname, basename = os.path.split(args.config)
	stem, ext = os.path.splitext(basename)

	key = stem

	logger.info("Key: %s", key)

	repo_path = "tmp-sct-data-urls/repos/{}".format(key)
	repo = pygit2.init_repository(repo_path)

	cmd = ["git", "remote", "add", "origin", "git@github.com:sct-data/{}.git".format(key)]
	subprocess.run(cmd, cwd=repo_path)

	if 0:
		logger.info("- Delete repo")

		url = "https://api.github.com/repos/sct-data/{}".format(key)
		headers = {
		 "Authorization": "token {}".format(GH_TOKEN),
		}

		req = urllib.request.Request(url, headers=headers, method="DELETE")
		with urllib.request.urlopen(req) as f:
			if f.getcode() != 204:
				raise RuntimeError("Ooops: %d / %s", f.getcode(), f.read())

	if 0:
		logger.info("- Create repo")

		url = "https://api.github.com/orgs/sct-data/repos"
		headers = {
		 "Authorization": "token {}".format(GH_TOKEN),
		 "Content-Type": "application/json",
		}

		payload = json.dumps({"name": key, "homepage": "https://github.com/neuropoly/spinalcordtoolbox"}).encode("utf-8")

		req = urllib.request.Request(url, headers=headers, method="POST", data=payload)
		with urllib.request.urlopen(req) as f:
			if f.getcode() != 201:
				raise RuntimeError("Ooops: %d / %s", f.getcode(), f.read())
			ret = json.loads(f.read().decode('utf-8'))
			logger.info("Repo creation sez: %s", ret)

	with io.open(args.config, "r", encoding="utf-8") as fi:
		root = yaml.safe_load(fi)

	parents = []

	for entry in root:
		res = archive_to_tree(repo, entry["urls"])
		if res is None:
			# no data
			continue
		archive_path, tree, t_max = res
		author_name = entry["commit"]["author_name"]
		author_email = entry["commit"]["author_email"]
		author_time = int(t_max)
		author = pygit2.Signature(author_name, author_email, author_time)
		committer = author

		logger.info("- %s", entry["commit"]["author_time"])

		msg = "Auto-generated commit for originally unversioned bundle"
		msg += "\n\n"
		msg += "SCT commit: {}\n".format(entry["commit"]["id"])
		msg += "SCT commit message:\n{}\n".format(entry["commit"]["message"])
		c = repo.create_commit('refs/heads/master', author, committer, msg, tree, parents)

		with io.open(archive_path + ".filename", "r", encoding="utf-8") as fi:
			archive_filename = fi.read()


		if archive_filename.startswith("PAM50_"):
			m = re.match(r"^PAM50_(?P<date>\d{8})\.zip$", archive_filename)
		else:
			m = re.match(r"^(?P<date>\d{8})_.*$", archive_filename)

		if m is None:
			logger.exception("Can't guess revision from %s", archive_filename)

		if entry["commit"]["id"] == "399c0a679264945e6c41fd7e80fd4d39320c21ff":
			# Incorrect filename in download
			guessed_revision = "20161128"
		elif archive_filename == "PAM50.zip":
			guessed_revision = datetime.datetime.strptime(entry["commit"]["author_time"], "%Y-%m-%dT%H:%M:%SZ").strftime("%Y%m%d")
			logger.info(" Guessed revision from commit date: %s", guessed_revision)
		else:
			guessed_revision = m.group("date")
			logger.info(" Guessed revision from archive name: %s (%s)", guessed_revision, archive_filename)

		msg = "Auto-generated tag from bundle name “{}”".format(archive_filename)
		tag_name = "r{}".format(guessed_revision)
		t = repo.create_tag(tag_name, c, pygit2.GIT_OBJ_COMMIT, author, msg)

		parents = [c]

		cmd = ["git", "push", "origin", "master", "--tags", "--force"]
		subprocess.run(cmd, cwd=repo_path)

		if 1:
			logger.info(" - Create release")

			url = "https://api.github.com/repos/sct-data/{}/releases".format(key)
			headers = {
			 "Authorization": "token {}".format(GH_TOKEN),
			 "Content-Type": "application/json",
			}
			payload = json.dumps({"tag_name": tag_name, "name": tag_name, "draft": False, "prerelease": False}).encode("utf-8")
			req = urllib.request.Request(url, headers=headers, method="POST", data=payload)
			try:
				with urllib.request.urlopen(req) as f:
					if f.getcode() != 201:
						raise RuntimeError("Ooops: %d / %s", f.getcode(), f.read())
					ret = json.loads(f.read().decode('utf-8'))
					logger.info("ret: %s", ret)
					release_id = ret["id"]

				logger.info(" - Upload original archive as release asset")

				url = "https://uploads.github.com/repos/sct-data/{}/releases/{}/assets?name={}" \
				 .format(key, release_id, archive_filename)

				headers = {
				 "Authorization": "token {}".format(GH_TOKEN),
				 "Content-Type": "application/octet-stream",
				}

				with io.open(archive_path, "rb") as fi:
					payload = fi.read()
				req = urllib.request.Request(url, headers=headers, method="POST", data=payload)
				with urllib.request.urlopen(req) as f:
					if f.getcode() != 201:
						raise RuntimeError("Ooops: %d / %s", f.getcode(), f.read())
					ret = json.loads(f.read().decode('utf-8'))

			except urllib.error.HTTPError as e:
				if e.code != 422:
					raise

if __name__ == "__main__":
	res = main()
	raise SystemExit()

