"""Usuarios y sesiones de la app web.

- Contraseñas con scrypt (stdlib) y sal propia; comparación en tiempo constante.
- Sesión = token aleatorio en una cookie HttpOnly/Secure/SameSite=Strict; en la base solo su SHA-256.
- Fuerza bruta: tope de intentos fallidos por usuario y por IP en una ventana de tiempo.

Gestión de usuarios (en el servidor):
    python -m patagonia_land.auth set-password <usuario>    # crea o cambia (pide la contraseña)
    python -m patagonia_land.auth list
    python -m patagonia_land.auth delete <usuario>
    python -m patagonia_land.auth logout-all <usuario>      # cierra todas sus sesiones
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import secrets
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from patagonia_land.db.models import LoginAttempt, User, UserSession

MIN_PASSWORD = 12
SESSION_TTL = timedelta(days=30)      # vencimiento absoluto
SESSION_IDLE = timedelta(days=7)      # sin uso por este tiempo => vence
ATTEMPT_WINDOW = timedelta(minutes=15)
MAX_FAILS_PER_USER = 5
MAX_FAILS_PER_IP = 20

_N, _R, _P = 2**15, 8, 1  # ~32 MB y ~50-100 ms por verificación


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              maxmem=64 * 1024 * 1024, dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


# Hash de una contraseña al azar: si el usuario no existe se verifica igual, para no revelarlo por el tiempo.
_DUMMY = hash_password(secrets.token_hex(16))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_username(username: str) -> str:
    return username.strip().lower()[:64]


# ----------------------------------------------------------------------------- login
def retry_after(s: Session, username: str, ip: str) -> int:
    """Segundos que hay que esperar antes de otro intento (0 = se puede intentar)."""
    since = datetime.now(UTC) - ATTEMPT_WINDOW
    fails = select(LoginAttempt.at).where(LoginAttempt.success.is_(False), LoginAttempt.at > since)
    by_user = s.scalars(fails.where(LoginAttempt.username == username).order_by(LoginAttempt.at)).all()
    by_ip = s.scalars(fails.where(LoginAttempt.ip == ip).order_by(LoginAttempt.at)).all()
    waits = []
    if len(by_user) >= MAX_FAILS_PER_USER:
        waits.append(by_user[-MAX_FAILS_PER_USER] + ATTEMPT_WINDOW)
    if len(by_ip) >= MAX_FAILS_PER_IP:
        waits.append(by_ip[-MAX_FAILS_PER_IP] + ATTEMPT_WINDOW)
    if not waits:
        return 0
    return max(1, int((max(waits) - datetime.now(UTC)).total_seconds()) + 1)


def authenticate(s: Session, username: str, password: str, ip: str) -> User | None:
    username = normalize_username(username)
    user = s.scalar(select(User).where(User.username == username))
    ok = verify_password(password, user.password_hash if user else _DUMMY) and user is not None
    s.add(LoginAttempt(username=username, ip=ip, success=ok))
    # Limpieza ocasional del historial de intentos.
    if secrets.randbelow(50) == 0:
        s.execute(delete(LoginAttempt).where(LoginAttempt.at < datetime.now(UTC) - timedelta(days=30)))
    if not ok:
        return None
    user.last_login_at = datetime.now(UTC)
    return user


def create_session(s: Session, user: User, ip: str | None, user_agent: str | None) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    s.add(UserSession(token_hash=_token_hash(token), user_id=user.id, expires_at=now + SESSION_TTL,
                      ip=ip, user_agent=(user_agent or "")[:300]))
    s.execute(delete(UserSession).where(UserSession.expires_at < now))
    return token


def session_user(s: Session, token: str) -> User | None:
    sess = s.get(UserSession, _token_hash(token))
    now = datetime.now(UTC)
    if not sess or sess.expires_at < now or sess.last_seen_at < now - SESSION_IDLE:
        return None
    if sess.last_seen_at < now - timedelta(minutes=10):
        sess.last_seen_at = now
    return s.get(User, sess.user_id)


def end_session(s: Session, token: str) -> None:
    s.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))


def users_exist(s: Session) -> bool:
    return bool(s.scalar(select(func.count()).select_from(User)))


# ----------------------------------------------------------------------------- CLI
def _cli(argv: list[str]) -> int:
    from patagonia_land.db.session import session_scope

    if len(argv) < 1 or argv[0] not in ("set-password", "list", "delete", "logout-all"):
        print(__doc__)
        return 2
    cmd = argv[0]
    with session_scope() as s:
        if cmd == "list":
            for u in s.scalars(select(User).order_by(User.username)):
                n = s.scalar(select(func.count()).select_from(UserSession).where(UserSession.user_id == u.id))
                print(f"{u.username}\túltimo ingreso: {u.last_login_at or '—'}\tsesiones: {n}")
            return 0
        if len(argv) < 2:
            print("Falta el usuario")
            return 2
        username = normalize_username(argv[1])
        user = s.scalar(select(User).where(User.username == username))
        if cmd == "set-password":
            pw = getpass.getpass("Contraseña nueva (mín. 12 caracteres): ")
            if len(pw) < MIN_PASSWORD:
                print("La contraseña debe tener al menos 12 caracteres")
                return 1
            if getpass.getpass("Repetila: ") != pw:
                print("No coinciden")
                return 1
            if user:
                user.password_hash = hash_password(pw)
                s.execute(delete(UserSession).where(UserSession.user_id == user.id))  # cierra sesiones abiertas
                print(f"Contraseña de {username} cambiada; se cerraron sus sesiones.")
            else:
                s.add(User(username=username, password_hash=hash_password(pw)))
                print(f"Usuario {username} creado.")
            return 0
        if not user:
            print(f"No existe el usuario {username}")
            return 1
        if cmd == "delete":
            s.delete(user)
            print(f"Usuario {username} borrado.")
        else:
            s.execute(delete(UserSession).where(UserSession.user_id == user.id))
            print(f"Sesiones de {username} cerradas.")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
