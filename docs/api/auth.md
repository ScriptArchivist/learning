```md
# Auth API

## Service

`identity-service`

Base URL example:
- local: `http://localhost:8001`
- home LAN: `http://<LAN_IP>:8001`

Swagger:
- `/docs`

---

## Endpoint

### POST `/auth/login`

Вход пользователя по username/password.

### Request body

```json
{
  "username": "string",
  "password": "string"
}
Fields

username — логин пользователя

password — пароль пользователя

Response

Фактический response формируется функцией identity.service.auth_service.login(...).

Для Flutter важно:

сохранить access token, если он возвращается сервисом

использовать его в Authorization: Bearer <token> для защищённых endpoints

Error handling

При неуспешной авторизации сервис возвращает ошибку FastAPI / HTTPException в соответствии с логикой auth service.

Flutter-клиенту рекомендуется:

обрабатывать 401/403

показывать пользовательское сообщение об ошибке входа

Practical Flutter flow

Пользователь вводит логин и пароль

Flutter вызывает POST /auth/login

Сохраняет токен

Передаёт токен в последующих запросах

Headers

Для приватных endpoints backend использует:

Authorization: Bearer <JWT>
Notes

На текущем этапе identity-service реализует минимальный auth flow.
Документацию клиента следует строить так, чтобы auth-слой Flutter был изолирован и мог быть расширен позже без переписывания остального приложения.