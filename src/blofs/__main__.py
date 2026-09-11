import json
import logging
import pathlib

import click
import geojson
import mfusepy as fuse
import uvicorn

import blofs
import blofs.tarfs
import blofs.tarfs_http

def get_logger() -> logging.Logger:
    return logging.getLogger("blofs")


CONTEXT_SETTINGS = {
    "show_default":True
}

@click.group(
    invoke_without_command=True,
    context_settings = CONTEXT_SETTINGS,
    help=(
        "BLOFS CLI for binary large object container indexing and access."
        f"\nVersion: {blofs.__version__}"
    )
)
@click.option("-l", "--loglevel", default="INFO", help="Set the logging level (INFO)")
@click.option("--version", is_flag=True, help="Show version and exit.")
@click.pass_context
def main(ctx: click.Context, loglevel:str, version:bool) -> None:
    """BLOFS CLI."""
    if version:
        print(f"BLOFS version {blofs.__version__}")
        ctx.exit(0)
    ctx.ensure_object(dict)
    loglevel = loglevel.strip().upper()
    assert loglevel in ("DEBUG", "INFO", "ERROR", "WARNING", "CRITICAL")
    numeric_level = getattr(logging, loglevel)
    logging.basicConfig(level=numeric_level)
    logger = get_logger()
    logger.setLevel(numeric_level)


@main.command("index")
@click.pass_context
@click.argument(
    "source",
    type=click.Path(path_type=pathlib.Path, exists=True, file_okay=True)
)
@click.argument(
    "metadata",
    type=click.Path(path_type=pathlib.Path, file_okay=True)
)
@click.argument(
    "dest",
    type=click.Path(path_type=pathlib.Path, exists=False)
)
def index_container(
    ctx,
    source:pathlib.Path,
    metadata:pathlib.Path,
    dest:pathlib.Path
)->None:
    """Create an index for the specified uncompressed TAR file."""
    blofs.tarfs.create_tar_index(source, metadata, dest)


@main.command("mount")
@click.pass_context
@click.argument(
    "source",
    type=click.Path(path_type=pathlib.Path, file_okay=True)
)
@click.argument(
    "manifest",
    type=click.Path(path_type=pathlib.Path, file_okay=True)
)
@click.argument(
    "mountpoint",
    type=click.Path(path_type=pathlib.Path, file_okay=False)
)
@click.option(
    "-f", "--foreground",
    is_flag=True,
    help="Mount as foreground process"
)
def mount_container(ctx, source, manifest, mountpoint, foreground) -> None:
    """Mount a TAR container as a local file system."""
    fs = blofs.tarfs.TarManifestFileSystem(
        tar_path=source,
        manifest_path=manifest
    )
    fuse.FUSE(
        blofs.tarfs.FSSpecFUSE(fs),
        str(mountpoint),
        foreground=foreground,
        ro=True
    )


@main.command("serve")
@click.pass_context
@click.argument(
    "source",
    type=click.Path(path_type=pathlib.Path, file_okay=True)
)
@click.argument(
    "manifest",
    type=click.Path(path_type=pathlib.Path, file_okay=True)
)
@click.option(
    "--pid",
    default="id",
    help="Base path for content."
)
def serve_http(ctx, source, manifest, pid) -> None:
    fs = blofs.tarfs.TarManifestFileSystem(
        tar_path=source,
        manifest_path=manifest
    )
    features = []
    for key,value in fs.files.items():
        if value["type"] == "file":
            pt = geojson.Point((value["longitude"], value["latitude"]))
            feat = geojson.Feature(
                geometry=pt,
                properties={"image":f"/{pid}/{value['name']}"}
            )
            features.append(feat)
    geodata = geojson.FeatureCollection(features)
    app_instance = blofs.tarfs_http.create_app(
        pid,
        fs,
        json.loads(geojson.dumps(geodata))
    )
    uvicorn.run(
        app_instance,
        host="127.0.0.1",
        port=8888,
    )

if __name__ == "__main__":
    main() # type: ignore[call-arg]
