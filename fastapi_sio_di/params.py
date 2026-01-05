class SID(str):
    """
    Marker class to indicate a 'sid' dependency.

    Used as a type annotation to signal that the parameter
    should be resolved from the socket session ID.

    Examples:
        @sio.on("message")
        async def message(sid: SID):
            print(sid)
    """


class Environ(dict):
    """
    Marker class to indicate an 'environ' dependency.

    Used as a type annotation to signal that the parameter
    should be resolved from the socket environment/context.

    Only takes effect during the 'connect' event.

    Examples:
        @sio.on("connect")
        async def connect(environ: Environ):
            print(environ)
    """
