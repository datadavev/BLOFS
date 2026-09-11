# BLOFS

[![Actions Status][actions-badge]][actions-link]
[![PyPI version][pypi-version]][pypi-link]
[![PyPI platforms][pypi-platforms]][pypi-link]

Binary Large Object File System with spatial awareness.

This is an exploration of leveraging the fsspec for serving custom content via FUSE and over HTTP.

This implementation creates a manifest for an uncompressed bundle of files, and includes in the manifest basic spatial properties (longitude and latitude). The tar file can be mounted as a file system, with the driver using the manifest to provide an index into the tar for navigation. The tar can also be served as a folder of content over http, with the manifest providing the file locations similarly to the FUSE mount.

The general goal is to facilitate the distribution of many (perhaps thousands or millions) files by bundling into two files: the tar and the manifest.

In this example, an ndjson file is used as the manifest, though other formats such as sqlite or parquet would also be effective.


## Installation

From source:
```bash
git clone https://github.com/datadavev/BLOFS
cd BLOFS
python -m pip install .
```

## Usage

Given a folder with contents:

```
$ tree
.
├── a
│   ├── img1.jpg
│   ├── img2.jpg
│   └── img3.jpg
└── metadata.ndjson

$ cat metadata.ndjson
{"name":"a/img1.jpg","latitude":37.5,"longitude":-122.0}
{"name":"a/img2.jpg","latitude":-17.5,"longitude":-149.8}
{"name":"a/img3.jpg","latitude":39.0,"longitude":-76.6}
```

Create an uncompressed tar file of `a`:
```
$ tar --no-mac-metadata --no-xattrs -cvf test1.tar a
```

Create a manifest for the uncompressed tar, including metadata properties in the manifest (metadata entries are identified by file name):
```
$ blofs index test1.tar metadata.ndjson manifest.ndjson
```

Mount the tarfile:
```
$ mkdir mnt
$ blofs mount test1.tar manifest.ndjson mnt
```

Show the mountpoint structure:
```
$ tree mnt
mnt
└── a
    ├── img1.jpg
    ├── img2.jpg
    └── img3.jpg
```

Unmount:

```
$ umount mnt
```


Serve the tar over http:
```
blofs serve test1.tar manifest.ndjson --pid "my_pid"
```

Then in a browser open:

- `http://localhost:8888/my_pid` for a spatial view
- `http://localhost:8888/my_pid/geojson` for a generated geojson
- `http://localhost:8888/my_pid/a/img1.jpg` to open `a/img1.jpg` by loading from the tar.


## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for instructions on how to contribute.

## License

Distributed under the terms of the [Apache license](LICENSE).


<!-- prettier-ignore-start -->
[actions-badge]:            https://github.com/datadavev/BLOFS/workflows/CI/badge.svg
[actions-link]:             https://github.com/datadavev/BLOFS/actions
[pypi-link]:                https://pypi.org/project/BLOFS/
[pypi-platforms]:           https://img.shields.io/pypi/pyversions/BLOFS
[pypi-version]:             https://img.shields.io/pypi/v/BLOFS
<!-- prettier-ignore-end -->
