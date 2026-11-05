# Auth design notes

**Why argon2.** Passwords are hashed with argon2id (via `pwdlib`). It is memory-hard, so a stolen database is expensive to brute-force on GPUs, unlike fast hashes such as SHA-256. Each hash embeds its own random salt and parameters, so they can be raised later without a schema change.

**Why httpOnly cookies, not localStorage.** Anything in localStorage is readable by any script on the page, so one XSS bug leaks the session. An httpOnly cookie is invisible to JavaScript; the browser attaches it itself. Tokens never appear in response bodies. The price is CSRF exposure, handled with `SameSite=Lax`, a separate JS-readable `csrf_token` cookie, and `Secure` in production.

**Why short access plus long refresh.** The access JWT lives 15 minutes and is verified without a database lookup, so a leaked one is useful only briefly. The refresh token lives 30 days, is opaque, and is stored (as a sha256 hash) server-side, so it can be revoked. The user stays signed in without a long-lived bearer credential on every request. The access cookie is scoped to `/api` and the refresh cookie to `/api/auth`, so the long-lived token is sent only where it is needed.

**Rotation and reuse detection.** Every refresh retires the presented token and issues a new one in the same family. A retired token should never come back. If one does (after the grace window), someone has a copy, either the attacker or the real user after theft, so the whole family is revoked and everyone must log in again. That revocation is committed even though the response is a 401 (the router returns the response instead of raising, because `get_db` rolls back on exceptions).

**The 10 second grace.** Two browser tabs can fire a refresh at the same moment with the same cookie; the loser would present an already-rotated token. If a retired token is replayed within 10 seconds of its rotation, the request gets a 401 but the family is left alone, so the winner's new token keeps working. Rows are locked (`SELECT ... FOR UPDATE`) so truly concurrent rotations serialise.

**Pinning the algorithm.** Decoding passes `algorithms=["HS256"]` explicitly and requires the claims `sub, exp, iat, jti, type`, with `type == "access"`. Letting the token's own header pick the algorithm enables the classic `alg: none` and key-confusion attacks, and the `type` check stops a refresh-style token from being used as an access token.

**One error message.** Login answers `Invalid email or password` for both a wrong password and an unknown email, and hashes a dummy password for unknown emails, so neither the response nor its timing reveals which accounts exist.

**Server-side logout.** Clearing cookies only affects the browser that did it. Logout also revokes the refresh token in the database, so a copied refresh cookie stops working immediately. The access JWT is stateless and stays valid until it expires (at most 15 minutes); that is the deliberate trade-off for not hitting the database on every request.
