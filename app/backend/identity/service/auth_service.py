from sqlalchemy.orm import Session

from db.models import User
from errors import NotFoundError
from identity.service.jwt_service import create_access_token, create_refresh_token
from identity.service.password_service import verify_password
import time
from src.metrics import inc_auth_login, observe_auth_login_duration
from src.metrics import get_service_name


def login(db: Session, username: str, password: str):
    import time
    from src.metrics import inc_auth_login, observe_auth_login_duration, get_service_name

    service_name = get_service_name("identity-service")
    start = time.perf_counter()

    try:
        user = db.query(User).filter(User.username == username).first()

        if not user:
            inc_auth_login(service_name, "fail")
            duration = time.perf_counter() - start
            observe_auth_login_duration(service_name, "fail", duration)
            raise NotFoundError("Invalid credentials")

        if not verify_password(password, user.hashed_password):
            inc_auth_login(service_name, "fail")
            duration = time.perf_counter() - start
            observe_auth_login_duration(service_name, "fail", duration)
            raise NotFoundError("Invalid credentials")

        access = create_access_token(user.id, user.role)
        refresh = create_refresh_token()

        inc_auth_login(service_name, "success")
        duration = time.perf_counter() - start
        observe_auth_login_duration(service_name, "success", duration)

        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": 1800,
        }

    except Exception:
        # если что-то неожиданное (DB, токены и т.д.)
        inc_auth_login(service_name, "fail")
        duration = time.perf_counter() - start
        observe_auth_login_duration(service_name, "fail", duration)
        raise