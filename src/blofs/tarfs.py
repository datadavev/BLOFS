"""Implements objects for container entries and collections."""

import errno
import logging
import os
import pathlib
import stat
import tarfile

import fsspec
from fsspec.spec import AbstractBufferedFile
import mfusepy as fuse
import ndjson


def get_logger()->logging.Logger:
    return logging.getLogger("blofs.entries")

IGNORE_ENTRIES = [".DS_Store", ]

def is_ignored(name:str) -> bool:
    parts = name.rsplit("/", 1)
    return parts[-1] in IGNORE_ENTRIES

def create_tar_index(
    source_tar:pathlib.Path,
    source_metadata: pathlib.Path,
    dest:pathlib.Path
)->int:
    with source_metadata.open("r", encoding="utf-8") as md_source:
        metadata = ndjson.load(md_source)
    # create an index for fast lookup of path
    metadata_map = {}
    for i in range(0, len(metadata)):
        metadata_map[metadata[i]["name"]] = i
    # create the manifest
    manifest = []
    with tarfile.open(source_tar, "r") as tar:
        for member in tar.getmembers():
            if is_ignored(member.name):
                continue
            entry:dict[str,str|int|float] = {
                "name": member.name,
            }
            if member.isfile():
                entry["offset"] = member.offset_data
                entry["size"] = member.size
                entry["modified"] = member.mtime
                entry["type"] = "file"
                meta = metadata[metadata_map[member.name]]
                entry.update(meta)
            else:
                entry["type"] = "directory"
                entry["offset"] = member.offset_data
                entry["size"] = 0
            manifest.append(entry)

    # output manifest to destination ndjson file
    with dest.open(mode="w", encoding="utf-8") as destf:
        ndjson.dump(manifest, destf)
    return len(manifest)


class TarManifestFileSystem(fsspec.AbstractFileSystem):
    """Custom fsspec filesystem backed by a precomputed tar manifest."""
    protocol = "tarmanifest"

    def __init__(self, tar_path, manifest_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tar_path = tar_path
        with open(manifest_path, "r") as f:
            self.manifest = ndjson.load(f)

        self.dirs = set()
        self.files = {}

        for meta in self.manifest:
            spath = meta["name"].lstrip("/")
            self.files[spath] = meta
            parts = spath.split("/")
            for i in range(1, len(parts)):
                self.dirs.add("/".join(parts[:i]))
        self.dirs.add("")

    def _ls(self, path, detail=True, **kwargs):
        path = path.lstrip("/").rstrip("/")
        results = []
        prefix = path + "/" if path else ""
        seen = set()

        for fpath, meta in self.files.items():
            if path == "" or fpath.startswith(prefix):
                rel = fpath[len(prefix):] if prefix else fpath
                parts = rel.split("/")
                name = parts[0]
                if name and name not in seen:
                    seen.add(name)
                    full_name = f"{path}/{name}" if path else name
                    if len(parts) == 1:
                        results.append({
                            "name": full_name,
                            "size": meta["size"],
                            "type": "file",
                            "offset": meta["offset"]
                        })
                    else:
                        results.append({
                            "name": full_name,
                            "size": 0,
                            "type": "directory"
                        })

        for d in self.dirs:
            if path == "" or (d.startswith(prefix) and d != path):
                rel = d[len(prefix):] if prefix else d
                parts = rel.split("/")
                name = parts[0]
                if name and name not in seen:
                    seen.add(name)
                    full_name = f"{path}/{name}" if path else name
                    if len(parts) == 1:
                        results.append({
                            "name": full_name,
                            "size": 0,
                            "type": "directory"
                        })

        if not detail:
            return [r["name"] for r in results]
        return results

    def ls(self, path, detail=True, **kwargs):
        return self._ls(path, detail=detail, **kwargs)

    def info(self, path, **kwargs):
        path = path.lstrip("/")
        if path == "" or path in self.dirs:
            return {"name": path, "size": 0, "type": "directory"}
        if path in self.files:
            meta = self.files[path]
            return {
                "name": path,
                "size": meta["size"],
                "type": "file",
                "offset": meta["offset"]
            }
        msg = f"Path not found: {path}"
        raise FileNotFoundError(msg)

    def _open(self, path, mode="rb", **kwargs):
        path = path.lstrip("/")
        if path not in self.files:
            msg = f"File not found: {path}"
            raise FileNotFoundError(msg)
        return TarFileSeekableFile(self, path, mode=mode, **kwargs)


class TarFileSeekableFile(AbstractBufferedFile):
    """File-like object that reads slices of the tar archive using absolute byte
    offsets."""
    def __init__(self, fs, path, mode="rb", **kwargs):
        super().__init__(fs, path, mode=mode, **kwargs)
        if mode != "rb":
            msg = "Only read-only mode 'rb' is supported."
            raise NotImplementedError(msg)
        info = self.fs.info(path)
        self.offset = info["offset"]
        self.size = info["size"]
        self.tar_file = open(self.fs.tar_path, "rb")

    def _fetch_range(self, start, end):
        self.tar_file.seek(self.offset + start)
        return self.tar_file.read(end - start)

    def close(self):
        if hasattr(self, "tar_file") and self.tar_file:
            self.tar_file.close()
        super().close()


class FSSpecFUSE(fuse.Operations):
    """FUSE operations adapter using an fsspec filesystem instance."""
    def __init__(self, fs: fsspec.AbstractFileSystem):
        self.fs = fs
        self.fd_counter = 0
        self.open_files = {}

    def getattr(self, path, fh=None):
        try:
            info = self.fs.info(path)
        except FileNotFoundError:
            raise fuse.FuseOSError(errno.ENOENT)

        if info["type"] == "directory":
            st_mode = stat.S_IFDIR | 0o555
            st_size = 0
        else:
            st_mode = stat.S_IFREG | 0o444
            st_size = info["size"]

        return {
            'st_mode': st_mode,
            'st_nlink': 1,
            'st_size': st_size,
            'st_ctime': 0,
            'st_mtime': 0,
            'st_atime': 0,
        }

    def readdir(self, path, fh):
        entries = ['.', '..']
        try:
            listing = self.fs.ls(path, detail=False)
            for item in listing:
                entries.append(os.path.basename(item))
        except FileNotFoundError:
            raise fuse.FuseOSError(errno.ENOENT)
        return entries

    def open(self, path, flags):
        self.fd_counter += 1
        fd = self.fd_counter
        try:
            f = self.fs.open(path, "rb")
            self.open_files[fd] = f
        except FileNotFoundError:
            raise fuse.FuseOSError(errno.ENOENT)
        return fd

    def read(self, path, size, offset, fh):
        if fh not in self.open_files:
            raise fuse.FuseOSError(errno.EBADF)
        f = self.open_files[fh]
        f.seek(offset)
        return f.read(size)

    def release(self, path, fh):
        if fh in self.open_files:
            self.open_files[fh].close()
            del self.open_files[fh]
        return 0
