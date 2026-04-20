from pydantic import BaseModel


class ObjectResolverSettings(BaseModel):
    simbad_fallback: bool = False
    db_path: str = "~/.local/share/astrolol/object_resolver.db"
