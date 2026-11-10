"""In-memory cookie handoff. Cookie values are never part of the public API."""
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy


def cookie_jar(auth: dict | None) -> CookieJar:
    jar = CookieJar(policy=DefaultCookiePolicy(strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain))
    for c in (auth or {}).get("cookies", []):
        domain = c["domain"]
        expires = c.get("expires", -1)
        jar.set_cookie(Cookie(version=0, name=c["name"], value=c["value"], port=None, port_specified=False,
            domain=domain, domain_specified=domain.startswith("."), domain_initial_dot=domain.startswith("."),
            path=c.get("path", "/"), path_specified=True, secure=c.get("secure", False),
            expires=int(expires) if expires > 0 else None, discard=expires <= 0,
            comment=None, comment_url=None, rest={"HttpOnly": c.get("httpOnly", False)}, rfc2109=False))
    return jar


def apply_cookies(ydl, auth: dict | None):
    if not auth: return
    ydl.cookiejar.set_policy(DefaultCookiePolicy(strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain))
    for cookie in cookie_jar(auth): ydl.cookiejar.set_cookie(cookie)
