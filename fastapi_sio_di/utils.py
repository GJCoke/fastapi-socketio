import inspect
from typing import Annotated, Any, get_args, get_origin, Optional
from fastapi.params import Depends


def convert_to_depends(obj: Any) -> Optional[Depends]:
    if isinstance(obj, Depends):
        return Depends(obj.dependency, use_cache=obj.use_cache)
    return None


def extract_annotated_dependency(annotation: Any) -> Optional[Depends]:
    if get_origin(annotation) is not Annotated:
        return None

    for metadata in get_args(annotation)[1:]:
        if depend := convert_to_depends(metadata):
            return depend
    return None


def get_param_depend(param: inspect.Parameter) -> Optional[Depends]:
    if depend := extract_annotated_dependency(param.annotation):
        return depend

    return convert_to_depends(param.default)
