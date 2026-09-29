from app.subsonic.envelope import Payload
from app.subsonic.router import PublicContext, SubsonicContext, registry
from app.subsonic.schemas import License, OpenSubsonicExtension

# Extensions advertised to OpenSubsonic clients. Keep in sync with what is implemented.
OPENSUBSONIC_EXTENSIONS = [
    OpenSubsonicExtension(name="apiKeyAuthentication", versions=[1]),
    OpenSubsonicExtension(name="formPost", versions=[1]),
    OpenSubsonicExtension(name="indexBasedQueue", versions=[1]),
    OpenSubsonicExtension(name="songLyrics", versions=[1]),
]


@registry.endpoint("ping")
async def ping(ctx: SubsonicContext) -> Payload:
    return None


@registry.endpoint("getLicense")
async def get_license(ctx: SubsonicContext) -> Payload:
    return {"license": License(valid=True)}


# The OpenSubsonic spec requires this endpoint to work without authentication.
@registry.public_endpoint("getOpenSubsonicExtensions")
async def get_open_subsonic_extensions(ctx: PublicContext) -> Payload:
    return {"openSubsonicExtensions": OPENSUBSONIC_EXTENSIONS}
