import pathlib

import fsspec
import fastapi
import fastapi.responses
import fastapi.templating

import blofs.tarfs

fsspec.register_implementation("myfs", blofs.tarfs.TarManifestFileSystem, clobber=True)


TEMPLATES_PATH = pathlib.Path(__file__).parent / "templates"

def create_app(pid:str, fs, geodata) -> fastapi.FastAPI:
    app = fastapi.FastAPI()
    templates = fastapi.templating.Jinja2Templates(directory=TEMPLATES_PATH)
    app.state.config = {
        pid:{"fs": fs, "geo":geodata},
        "templates": templates
    }


    @app.get("/{pid}")
    async def read_manifest(request:fastapi.Request, pid):
        context = {
            "request": request,
            "pid": pid
        }
        return app.state.config["templates"].TemplateResponse(request, name="imgview.html", context=context)


    @app.get("/{pid}/geojson")
    async def geojson_viewer(request:fastapi.Request, pid):
        try:
            geo = request.app.state.config[pid]["geo"]
            return geo
        except Exception as e:
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_404_NOT_FOUND,
                detail=str(e)
            )


    @app.get("/{pid}/{item_path:path}")
    async def read_item(request:fastapi.Request, pid, item_path):
        try:
            fs = request.app.state.config[pid]["fs"]
            if not fs.exists(item_path):
                raise fastapi.HTTPException(
                    status_code=fastapi.status.HTTP_404_NOT_FOUND,
                    detail=f"Not found {item_path}"
                )
            file_object = fs.open(item_path, mode="rb")
            def iterfile():
                # 64 KB chunks
                chunk_size = 64 * 1024
                while chunk := file_object.read(chunk_size):
                    yield chunk
                # Ensure the fsspec file object is properly closed after streaming finishes
                file_object.close()
            return fastapi.responses.StreamingResponse(
                iterfile(),
                media_type="image/jpeg",
                #headers={
                #    "Content-Disposition":
                #        f"attachment; filename={item_path.split('/')[-1]}"
                #}
                )

        except Exception as e:
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_404_NOT_FOUND,
                detail=str(e)
            )

    return app
