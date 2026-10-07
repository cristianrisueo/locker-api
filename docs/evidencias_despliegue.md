# Evidencias del despliegue (F7c)

Verificación de extremo a extremo de Locker API **ya desplegada** en Google Cloud (F7 y F7b), hecha por Claude Code
por encargo del desarrollador. Solo lectura sobre la infraestructura: no se cambió nada del despliegue ni del código.
Cada verificación tiene un ID `V-nn`; la petición se escribe con variables en lugar de claves y nunca aparece ningún
código de recogida («código correcto» / «código incorrecto»).

## Entorno

| Dato                         | Valor                                                                                       |
| ---------------------------- | ------------------------------------------------------------------------------------------- |
| Fecha                        | 2026-10-07, de 07:52 a 08:27 UTC                                                             |
| URL principal                | <https://api.lockerapi.dev> (dominio propio, F7b)                                            |
| URL de Cloud Run (respaldo)  | <https://locker-api-sjqtezncha-ew.a.run.app>                                                 |
| Proyecto y región            | `locker-api-cristian` (`953827667605`), `europe-west1`; configuración de `gcloud` `locker-api` |
| Revisión del servicio        | `locker-api-00001-g7z`                                                                       |
| Revisión del worker pool     | `locker-worker-00001-p2l` (1 instancia, `python -m locker.outbox.worker`)                    |
| Imagen                       | `locker:d0e48ad5b4b603eb1d866e429e1cc9f3baee7bfc` (la de `v0.1.0-gcp1`)                       |
| Commit de `main`             | `8be31e2` (entre la imagen y `main` no cambia nada de `src/`, migraciones, `Dockerfile` ni dependencias) |
| Cloud SQL                    | `locker-db`, `POSTGRES_18`, `db-f1-micro`, `RUNNABLE`                                        |
| Recursos del proyecto        | Solo los de F7 y F7b: servicio `locker-api`, worker pool `locker-worker`, job `locker-migrate`, instancia `locker-db`, secretos `locker-api-keys`, `locker-pickup-secret` y `locker-db-url`, mapeo `api.lockerapi.dev` |

**Cómo se hicieron las pruebas.** Las claves y el secreto se leyeron con `gcloud secrets versions access latest` a
variables de entorno de cada proceso (`OPERATOR_KEY`, `CARRIER_KEY` de SEUR y `PICKUP_CODE_SECRET`), sin imprimirlos ni
escribirlos en disco. Las peticiones las hizo un script de Python con `httpx` fuera del repositorio, que registraba cada
una con las claves sustituidas por su variable. Los códigos de recogida se calcularon en local con
`locker.deliveries.pickup_code.derive`. Las URL son relativas a `https://api.lockerapi.dev` salvo que se diga otra cosa;
`{uuid}` es un UUID aleatorio que no existe.

**Datos creados** (no son secretos):

| Edificio                    | id                                     | Para qué                                                   |
| --------------------------- | -------------------------------------- | ---------------------------------------------------------- |
| Edificio Caducidad F7c      | `01a11559-a930-75bd-b0e2-3e02abb7e154` | V-42 a V-44 (una taquilla `S`)                             |
| Edificio Pruebas F7c        | `01a1155b-09d9-72e4-aea0-fe5157612a07` | V-09 a V-37 (3 `M`, 2 `S` y 1 `L`)                         |
| Edificio Concurrencia F7c   | `01a1155b-aefb-76a7-89e6-92ffe5a4ffbc` | V-38 (5 `M`)                                               |
| Edificio Idempotencia F7c   | `01a1155b-b2b7-7742-8665-fc4eca46cfa1` | V-39 y V-40 (2 `M`)                                        |
| Edificio Demo               | `01a1155c-630f-708c-8ffb-49a8881cfe6e` | V-45: para quien quiera probar el flujo; sin reservas      |

Además, la suite E2E de V-41 creó dos edificios «Edificio E2E».

## Verificaciones

### A. Disponibilidad y trazabilidad

| ID   | Qué se prueba | Petición | Esperado | Observado | Veredicto |
| ---- | ------------- | -------- | -------- | --------- | --------- |
| V-01 | `/health` por las dos URL, con `X-Request-ID` distinto | `GET /health` dos veces seguidas por el dominio y una por run.app | `200 {"status":"ok"}` y tres `X-Request-ID` distintos | `200 {"status":"ok"}` las tres veces; `X-Request-ID` `01a1155b-0475-75d9-af6e-1d3d6ed42820`, `01a1155b-0512-719b-a553-43eadb8f464d` y `01a1155b-05db-7504-b56a-3f6a5cdfd0a5` (UUID v7, distintos) | Cumple |
| V-02 | HTTPS con certificado válido | `curl -sI` y `curl -v` (sin `-k`) a `/health` | HTTP/2 o HTTP/3 y certificado válido | ALPN `h2`, `HTTP/2 200`, TLSv1.3. Certificado `CN=api.lockerapi.dev` de Google Trust Services (`WR3`), válido del 2026-10-06 al 2027-01-04, «SSL certificate verify ok» (`ssl_verify_result=0`). run.app también HTTP/2 con certificado válido. `curl -sI` (`HEAD`) responde `HTTP/2 405` con `allow: GET` (ver observaciones) | Cumple |
| V-03 | Arranque en frío | `curl -w "%{time_total}"` a `/health` tras escalar a cero, y otra seguida | La primera más lenta Sin tráfico desde las 08:00 UTC (una visita ajena), Monitoring marca 0 instancias desde las 08:15. A las 08:20:34, en frío: `200` en **5,73 s** (conexión 0,10 s, TLS 0,14 s, primer byte 5,73 s); el log del servicio dice «Starting new instance» a las 08:20:35. Justo después, en caliente: **0,139 s** y **0,134 s** | Cumple |
| V-04 | ¿La documentación es pública? | `GET /docs` y `GET /openapi.json` sin clave | Solo se documenta | `/docs` `200` y `/openapi.json` `200`: son **públicas**. El esquema lista las 8 rutas de §8.2 | Documentado |

### B. Seguridad

| ID   | Qué se prueba | Petición | Esperado | Observado | Veredicto |
| ---- | ------------- | -------- | -------- | --------- | --------- |
| V-05 | Sin clave | `GET /v1/buildings/{uuid}/capacity` sin `X-API-Key` | `401 UNAUTHENTICATED` | `401 {"code":"UNAUTHENTICATED","detail":"Falta la clave de API o no es válida"}` | Cumple |
| V-06 | Clave inválida | Igual, con `X-API-Key: clave-invalida-de-pruebas-f7c` | `401 UNAUTHENTICATED` | `401 {"code":"UNAUTHENTICATED","detail":"Falta la clave de API o no es válida"}` | Cumple |
| V-07 | El transportista no crea edificios | `POST /v1/buildings` · `X-API-Key: $CARRIER_KEY` · `{"name":"No debería crearse"}` | `403 FORBIDDEN` | `403 {"code":"FORBIDDEN","detail":"Esta clave no tiene permiso para esta operación"}` | Cumple |
| V-08 | El operador no reserva | `POST /v1/deliveries` · `X-API-Key: $OPERATOR_KEY` · `Idempotency-Key` nueva · cuerpo válido | `403 FORBIDDEN` | `403 {"code":"FORBIDDEN","detail":"Esta clave no tiene permiso para esta operación"}` | Cumple |

### C. Edificios, taquillas y capacidad

| ID   | Qué se prueba | Petición | Esperado | Observado | Veredicto |
| ---- | ------------- | -------- | -------- | --------- | --------- |
| V-09 | Alta de edificio | `POST /v1/buildings` · `$OPERATOR_KEY` · `{"name":"Edificio Pruebas F7c"}` | `201` con `id`, `name` y `country` | `201 {"id":"01a1155b-09d9-72e4-aea0-fe5157612a07","name":"Edificio Pruebas F7c","country":"ES"}` | Cumple |
| V-10 | Nombre vacío | `POST /v1/buildings` · `$OPERATOR_KEY` · `{"name":""}` | `422 VALIDATION_ERROR` | `422 {"code":"VALIDATION_ERROR","detail":"name: String should have at least 1 character"}` | Cumple |
| V-11 | 3 taquillas `M` | `POST /v1/buildings/{edificio}/lockers` · `$OPERATOR_KEY` · `{"size":"M","quantity":3}` | `201`, `M-01` a `M-03`, `FREE` | `201`, etiquetas `M-01`, `M-02`, `M-03`, todas `FREE` | Cumple |
| V-12 | Contador por talla | Igual con `{"size":"S","quantity":2}` y con `{"size":"L"}` | `S-01`, `S-02` y `L-01` | `201` y `201`; etiquetas `S-01`, `S-02` y `L-01` | Cumple |
| V-13 | Datos inválidos | Igual con `{"size":"XL","quantity":1}`, `{"size":"M","quantity":0}` y `{"size":"M","quantity":101}` | `422` las tres | `422` `size: Input should be 'S', 'M' or 'L'`; `422` `quantity: Input should be greater than or equal to 1`; `422` `quantity: Input should be less than or equal to 100` (las tres `VALIDATION_ERROR`) | Cumple |
| V-14 | Edificio inexistente | `POST /v1/buildings/{uuid}/lockers` · `$OPERATOR_KEY` · `{"size":"M","quantity":1}` | `404 NOT_FOUND` | `404 {"code":"NOT_FOUND","detail":"Edificio e1aa57ac-aa43-416e-980b-f3e38ca14896 no encontrado"}` | Cumple |
| V-15 | Capacidad | `GET /v1/buildings/{edificio}/capacity` con `$OPERATOR_KEY` y con `$CARRIER_KEY` | `200`, tallas `S`, `M`, `L` con total y libres | `200` las dos: `{"building_id":"01a1155b-09d9-...","sizes":[{"size":"S","total":2,"free":2},{"size":"M","total":3,"free":3},{"size":"L","total":1,"free":1}]}` | Cumple |
| V-16 | Capacidad de un edificio inexistente | `GET /v1/buildings/{uuid}/capacity` · `$OPERATOR_KEY` | `404` | `404 {"code":"NOT_FOUND","detail":"Edificio e1aa57ac-... no encontrado"}` | Cumple |

### D. Reserva e idempotencia (SEUR)

Cuerpo base A: `{"building_id":"<Edificio Pruebas F7c>","size":"M","tracking_ref":"F7C-A-8b5fe3","recipient":"vecino-a@example.com"}`.

| ID   | Qué se prueba | Petición | Esperado | Observado | Veredicto |
| ---- | ------------- | -------- | -------- | --------- | --------- |
| V-17 | Reserva | `POST /v1/deliveries` · `$CARRIER_KEY` · `Idempotency-Key: k1` (nueva) · cuerpo A | `201`, `PENDING`, sin `expires_at` | `201 {"id":"01a1155b-10f7-73d8-857e-2e7e86e4bcd9","status":"PENDING","building_id":"01a1155b-09d9-...","locker_label":"M-01","size":"M","carrier":"SEUR","tracking_ref":"F7C-A-8b5fe3","recipient":"vecino-a@example.com","deposited_at":null,"picked_up_at":null}`: los 10 campos de §8.4, sin `expires_at` | Cumple |
| V-18 | Repetición idéntica | La misma petición, misma `k1` | `201` con el mismo cuerpo; una sola taquilla ocupada | `201`, cuerpo **idéntico byte a byte**; capacidad `M` 2 libres de 3 | Cumple |
| V-19 | Misma clave, otro cuerpo | `k1` con `recipient` distinto | `422 IDEMPOTENCY_KEY_REUSED` | `422 {"code":"IDEMPOTENCY_KEY_REUSED","detail":"La clave ya se usó con otra petición distinta"}` | Cumple |
| V-20 | Sin `Idempotency-Key` | `POST /v1/deliveries` sin la cabecera | `422 VALIDATION_ERROR` | `422 {"code":"VALIDATION_ERROR","detail":"Idempotency-Key: Field required"}` | Cumple |
| V-21 | Paquete duplicado | Clave nueva, cuerpo A | `409 DUPLICATE_PACKAGE`, capacidad igual | `409 {"code":"DUPLICATE_PACKAGE","detail":"Este paquete ya tiene una reserva activa"}`; libres antes y después `S 2, M 2, L 1` | Cumple |
| V-22 | Sin talla exacta no hay reserva | Dos reservas `S` (claves y paquetes nuevos) y una tercera `S` con `Idempotency-Key: k22` | Las dos primeras `201`; la tercera `409 NO_LOCKER_AVAILABLE` aunque haya `M` libres | `S-01` y `S-02` reservadas; la tercera `409 {"code":"NO_LOCKER_AVAILABLE","detail":"No quedan taquillas de esta talla disponibles"}` con libres `S 0, M 2, L 1` | Cumple |
| V-23 | Una reserva fallida no guarda la clave | Tras recoger la entrega de `S-01` (código correcto, `200`), repetir la tercera `S` con `k22` y el mismo cuerpo | `201` | `201`, entrega `01a1155b-2942-7349-8fe8-2d9e25529b67` en `S-01`, `PENDING` | Cumple |

### E. Depositar y avisar

| ID   | Qué se prueba | Petición | Esperado | Observado | Veredicto |
| ---- | ------------- | -------- | -------- | --------- | --------- |
| V-24 | Depositar | `POST /v1/deliveries/{id}/deposit` · `$CARRIER_KEY`, para la entrega de V-17 (`M-01`) y la primera `S` (`01a1155b-153b-74a1-9eef-61f1e7a1a972`) | `200 DEPOSITED` con `deposited_at` | `200 {... "status":"DEPOSITED", ..., "deposited_at":"2026-10-07T07:54:13.802779Z","picked_up_at":null}` y `200 DEPOSITED` | Cumple |
| V-25 | Depositar otra vez | La misma petición sobre la entrega de V-17 | `200` sin cambios | `200`, cuerpo igual al de V-24 (mismo `deposited_at`) | Cumple |
| V-26 | Entrega inexistente | `POST /v1/deliveries/{uuid}/deposit` · `$CARRIER_KEY` | `404` | `404 {"code":"NOT_FOUND","detail":"Entrega d0e3b3d9-3b55-45c8-b742-5d76fe9baf1b no encontrada"}` | Cumple |
| V-27 | Un aviso por depósito en Cloud Logging | `gcloud logging read` del worker pool `locker-worker` desde las 07:50 UTC | Una línea por depósito de V-24; ninguna por V-25 | Dos líneas del logger `locker.notifier`: `event_id 01a1155b-17b2-77ca-85d9-fb30f16bedd9` / `delivery_id 01a1155b-10f7-73d8-857e-2e7e86e4bcd9` (07:54:14.204Z) y `event_id 01a1155b-1858-7054-9950-713bdf195150` / `delivery_id 01a1155b-153b-74a1-9eef-61f1e7a1a972` (07:54:14.274Z), unos 0,4 s después de depositar. El depósito repetido no generó ninguna más. Las otras dos líneas del periodo son los depósitos de V-40 y de la suite E2E (V-41). El texto del aviso no se reproduce porque lleva el código | Cumple |

### F. Consulta

| ID   | Qué se prueba | Petición | Esperado | Observado | Veredicto |
| ---- | ------------- | -------- | -------- | --------- | --------- |
| V-28 | SEUR consulta su entrega | `GET /v1/deliveries/{id de V-17}` · `$CARRIER_KEY` | `200` con los campos de §8.4 | `200`, el mismo cuerpo que V-24 (`DEPOSITED`) | Cumple |
| V-29 | El operador no consulta entregas | La misma con `$OPERATOR_KEY` | `403` | `403 {"code":"FORBIDDEN","detail":"Esta clave no tiene permiso para esta operación"}` | Cumple |

### G. Recoger (sin clave)

| ID   | Qué se prueba | Petición | Esperado | Observado | Veredicto |
| ---- | ------------- | -------- | -------- | --------- | --------- |
| V-30 | Código incorrecto | `POST /v1/deliveries/{id de V-17}/pickup` · `{"code":"<código incorrecto>"}` | `403 INVALID_PICKUP_CODE`, nada cambia | `403 {"code":"INVALID_PICKUP_CODE","detail":"Código de recogida incorrecto"}`; la consulta posterior devuelve la entrega igual, `DEPOSITED` | Cumple |
| V-31 | Código mal formado | `{"code":"12345"}` | `422` | `422 {"code":"VALIDATION_ERROR","detail":"code: String should match pattern '^[0-9]{6}$'"}` | Cumple |
| V-32 | Entrega inexistente | `POST /v1/deliveries/{uuid}/pickup` · `{"code":"000000"}` | `404` | `404 {"code":"NOT_FOUND","detail":"Entrega 65fba349-517f-47e4-bbcf-dd26baa5ca22 no encontrada"}` | Cumple |
| V-33 | Sin depositar | Recoger la segunda `S` (`PENDING`, `01a1155b-15e2-7470-94c5-485ebaa0df2e`) con su código correcto | `409 INVALID_STATE` | `409 {"code":"INVALID_STATE","detail":"La entrega no está en un estado que permita esta operación"}` | Cumple |
| V-34 | Recogida correcta | Entrega de V-17 · `{"code":"<código correcto>"}` | `200 PICKED_UP`, la taquilla vuelve a `FREE` | `200 {... "status":"PICKED_UP", ..., "deposited_at":"2026-10-07T07:54:13.802779Z","picked_up_at":"2026-10-07T07:54:15.837368Z"}`; `M` libres de 2 a 3 | Cumple |
| V-35 | Recoger otra vez | La misma petición | `409 INVALID_STATE` | `409 {"code":"INVALID_STATE",...}` | Cumple |
| V-36 | Depositar una entrega recogida | `POST /v1/deliveries/{id de V-17}/deposit` · `$CARRIER_KEY` | `409 INVALID_STATE` | `409 {"code":"INVALID_STATE",...}` | Cumple |
| V-37 | El código no sale en ninguna respuesta | Revisión de las respuestas de V-17, V-24, V-28 y V-34 | Ningún campo es el código | Ningún valor de ningún campo (ni el texto completo de la respuesta) contiene el código de su entrega. El arnés además falla si un código aparece en cualquier respuesta: no saltó en ninguna de las peticiones | Cumple |

### H. Concurrencia real contra el despliegue

Hilos desde la máquina del desarrollador, N ≤ 10.

| ID   | Qué se prueba | Petición | Esperado | Observado | Veredicto |
| ---- | ------------- | -------- | -------- | --------- | --------- |
| V-38 | 10 reservas a la vez para 5 taquillas | Edificio nuevo con 5 `M`; 10 `POST /v1/deliveries` simultáneos (`$CARRIER_KEY`, claves y paquetes distintos) | 5 × `201` y 5 × `409 NO_LOCKER_AVAILABLE`, 5 taquillas distintas | 5 × `201` con `M-01` a `M-05` (todas distintas) y 5 × `409 NO_LOCKER_AVAILABLE`; capacidad `M` 0 libres de 5 | Cumple |
| V-39 | Misma `Idempotency-Key` a la vez | Edificio con 2 `M`; dos `POST /v1/deliveries` simultáneos con la misma clave y el mismo cuerpo | Los dos `201` con el mismo cuerpo; una sola taquilla ocupada | `201` y `201`, cuerpos idénticos; capacidad `M` 1 libre de 2 | Cumple |
| V-40 | Dos recogidas a la vez | Depositar la entrega de V-39 y lanzar dos `pickup` simultáneos con el código correcto | Una `200` y una `409` | `200` y `409 INVALID_STATE`; capacidad final `M` 2 libres de 2 | Cumple |

### I. Suite E2E contra producción

| ID   | Qué se prueba | Petición | Esperado | Observado | Veredicto |
| ---- | ------------- | -------- | -------- | --------- | --------- |
| V-41 | `test_smoke.py`, `test_delivery_flow.py` y `test_replicas_concurrency.py` contra el despliegue | `API_KEYS` y `PICKUP_CODE_SECRET` leídas de Secret Manager a variables de entorno (sin `.env` ni ficheros); `BASE_URLS` según abajo; `uv run pytest ...` | Verde | Con `BASE_URLS=https://api.lockerapi.dev`: `test_smoke.py` **1 passed**. Con `BASE_URLS=https://api.lockerapi.dev,https://locker-api-sjqtezncha-ew.a.run.app`: los tres ficheros, **4 passed** en 3,40 s | Cumple |

`tests/e2e/conftest.py` lee `BASE_URLS` del entorno y las claves con `get_settings()`, es decir, `API_KEYS` y
`PICKUP_CODE_SECRET` del entorno (que tienen prioridad sobre el `.env`; `DATABASE_URL` se exige pero estos tres
ficheros no la usan). `test_delivery_flow.py` y `test_replicas_concurrency.py` exigen al menos dos URL en `BASE_URLS`
(alternan «réplicas»), así que se pasaron las dos entradas al mismo servicio: el dominio propio y la URL de run.app.

No se ejecutaron aquí `test_worker_drains_outbox.py` ni `test_reservation_expiry.py`: necesitan conectarse a la base de
datos con `DATABASE_URL`, y Cloud SQL no tiene redes autorizadas. Los cubre `make e2e` en local; en producción, el aviso
lo cubre V-27 y la caducidad V-42 a V-44.

### J. Caducidad (F6)

Reserva `S` en el Edificio Caducidad F7c: entrega `01a11559-aac9-76ca-ab09-9f7b3b593ce5`, paquete `F7C-EXP-18250213`,
reservada a las **07:52:40 UTC** (`201 PENDING`, `S-01`; capacidad `S` 0 libres de 1).

| ID   | Qué se prueba | Petición | Esperado | Observado | Veredicto |
| ---- | ------------- | -------- | -------- | --------- | --------- |
| V-42 | La reserva caduca | `GET /v1/deliveries/01a11559-aac9-76ca-ab09-9f7b3b593ce5` · `$CARRIER_KEY`, a los 31,5 minutos (08:24:05 UTC) | `200` con `status` `EXPIRED` | `200 {"id":"01a11559-aac9-...","status":"EXPIRED","locker_label":"S-01",...,"deposited_at":null,"picked_up_at":null}`. El log del worker (`locker.deliveries.expiration`, «Reserva caducada: su taquilla queda libre») la registra a las 08:22:41 UTC, 30 minutos justos después de reservar | Cumple |
| V-43 | Depositar una caducada | `POST /v1/deliveries/01a11559-aac9-.../deposit` · `$CARRIER_KEY` | `409 INVALID_STATE` | `409 {"code":"INVALID_STATE","detail":"La entrega no está en un estado que permita esta operación"}` | Cumple |
| V-44 | La taquilla queda libre y el paquete se puede volver a reservar | `GET /v1/buildings/01a11559-a930-.../capacity` y `POST /v1/deliveries` con el mismo cuerpo y una clave nueva | `S` libre; `201` | Capacidad `{"sizes":[{"size":"S","total":1,"free":1}]}`; la nueva reserva del mismo paquete `F7C-EXP-18250213`: `201`, entrega `01a11576-7e98-7090-8644-457d6af742db` en `S-01`, `PENDING` | Cumple |

### K. Edificio de demostración

| ID   | Qué se prueba | Petición | Esperado | Observado | Veredicto |
| ---- | ------------- | -------- | -------- | --------- | --------- |
| V-45 | Edificio Demo sin reservas | `POST /v1/buildings` `{"name":"Edificio Demo"}` y tres altas de taquillas (`S` ×2, `M` ×3, `L` ×2), con `$OPERATOR_KEY` | `201`; capacidad todo libre | `201`; capacidad `[{"size":"S","total":2,"free":2},{"size":"M","total":3,"free":3},{"size":"L","total":2,"free":2}]`. No se reservó nada en él | Cumple |

**Edificio Demo: `01a1155c-630f-708c-8ffb-49a8881cfe6e`.** Para probar el flujo hacen falta las claves (en Secret
Manager, `locker-api-keys`) y, para recoger, el código, que llega en el aviso del log del worker (o se calcula con
`pickup_code.derive` y el secreto de `locker-pickup-secret`):

```bash
# 1. Reservar una taquilla M (SEUR). Guarda el "id" de la respuesta
curl -s -X POST https://api.lockerapi.dev/v1/deliveries \
  -H "X-API-Key: $CARRIER_KEY" -H "Idempotency-Key: $(uuidgen)" -H "Content-Type: application/json" \
  -d '{"building_id":"01a1155c-630f-708c-8ffb-49a8881cfe6e","size":"M","tracking_ref":"DEMO-001","recipient":"vecino@example.com"}'

# 2. Depositar el paquete (con el id de la reserva)
curl -s -X POST "https://api.lockerapi.dev/v1/deliveries/$DELIVERY_ID/deposit" -H "X-API-Key: $CARRIER_KEY"

# 3. Recoger con el código de seis cifras (sin clave)
curl -s -X POST "https://api.lockerapi.dev/v1/deliveries/$DELIVERY_ID/pickup" \
  -H "Content-Type: application/json" -d "{\"code\":\"$PICKUP_CODE\"}"
```

La capacidad se ve con `curl -s https://api.lockerapi.dev/v1/buildings/01a1155c-630f-708c-8ffb-49a8881cfe6e/capacity -H "X-API-Key: $OPERATOR_KEY"`.
Una reserva sin depositar caduca a los 30 minutos y libera su taquilla.

## Observaciones

**Resumen.** 45 verificaciones: 44 cumplen y V-04 se documenta (la documentación es pública). Ninguna falla y ninguna
queda sin verificar. Ningún `5xx` en toda la fase: unas 130 peticiones propias (125 con registro de petición en Cloud
Logging entre las 07:50 y las 08:27 UTC, más la suite E2E y las mediciones con `curl`).

**Arranque en frío.** Con 0 instancias mínimas, la primera petición tras escalar a cero tarda **unos 5,7 s** (arrancar
el contenedor, importar la aplicación y abrir el pool de conexiones con Cloud SQL por el socket); en caliente,
**unos 0,13 s** desde España. El servicio escaló a cero unos 15 minutos después de la última petición. Un cliente que
llame tras un rato sin tráfico debe tolerar esos segundos (el CD ya lo hace al calentar la API con reintentos).

**Latencias típicas** (en caliente):

- En el servidor (`httpRequest.latency` de Cloud Run, 109 peticiones de A a H): mediana **14 ms**, p95 **270 ms**,
  máximo 301 ms. Por encima de 100 ms solo quedan las 8 reservas simultáneas de V-38 que esperaron a otras (de 160 a 301 ms) y el `/health` del arranque de la fase (270 ms).
- Desde el cliente (España → `europe-west1`, con una conexión TLS nueva en cada petición): de **140 a 180 ms** de
  mediana en todas las operaciones (capacidad 147 ms, reservar 179 ms, depositar 160 ms, recoger 148 ms). Las 10
  reservas simultáneas de V-38 tardaron de 250 a 507 ms. Un caso aislado de 1,8 s en el cliente (V-35) tardó 10 ms en
  el servidor: fue la red.

**Comportamientos que conviene conocer** (no son fallos frente a las especificaciones):

1. **`HEAD /health` da `405`** (`allow: GET`). `curl -sI` usa `HEAD`; §7.12 solo define `GET`. Un servicio externo de
   monitorización que compruebe con `HEAD` vería la API caída.
2. **Los logs llegan a Cloud Logging sin `severity`.** El formato JSON de §7.11 usa el campo `level`, que Cloud Logging
   no reconoce: todas las líneas de la aplicación salen con gravedad por defecto, y filtrar por `severity>=ERROR` no
   encuentra los errores de la aplicación (sí se puede filtrar por `jsonPayload.level`).
3. **`/docs` y `/openapi.json` son públicas** (V-04). Las especificaciones no dicen nada; el esquema no contiene
   secretos.
4. **Hay tráfico ajeno.** A las 07:58:28 alguien pidió `GET /` (`404`) con un navegador; el dominio es público y sale en
   los registros de transparencia de certificados. Cada visita así despierta una instancia (sin coste relevante).
5. **Una sola instancia atendió toda la fase**, también las 10 reservas simultáneas de V-38: la protección que se vio
   funcionar es la de la base de datos (`FOR UPDATE SKIP LOCKED`, la restricción única y la fila de la clave de
   idempotencia) bajo peticiones concurrentes reales en un proceso. La concurrencia entre procesos distintos la prueba
   `make e2e` con dos réplicas en local.
6. **Caducidad puntual.** El worker caducó la reserva de V-42 a los 30 minutos justos (08:22:41 para una reserva de las
   07:52:40) y liberó su taquilla. Además caducaron las otras 11 reservas que la fase dejó sin depositar (2 en el
   Edificio Pruebas F7c, 5 en el de Concurrencia y 5 de la suite E2E), con su línea de log cada una, y sus taquillas
   volvieron a estar libres.
7. **HTTP/3**: el dominio propio responde por HTTP/2 y no anuncia HTTP/3 (`alt-svc`). V-02 pide «HTTP/2 o HTTP/3»:
   cumple con HTTP/2.

**Lo que no se ha podido verificar, y por qué:**

- **`503 SERVICE_UNAVAILABLE` de `/health`**: exigiría parar Cloud SQL, que está prohibido en esta fase. Lo cubren los
  tests de integración.
- **La propiedad de las entregas entre transportistas** (`404` al tocar la entrega de otro): solo existe la clave de
  SEUR. Lo cubren los tests de integración.
- **La caducidad forzada por SQL** y **el vaciado del outbox comprobado en la base de datos**
  (`test_reservation_expiry.py` y `test_worker_drains_outbox.py`): necesitan conectarse a la base de datos y Cloud SQL
  no tiene redes autorizadas. Los cubre `make e2e` en local; en producción se vio el resultado por la API y los logs
  (V-27 y V-42 a V-44).

**Datos que quedan en la base de datos.** Los edificios de la tabla del principio, sus entregas (recogidas o caducadas)
y los dos «Edificio E2E». La nueva reserva de V-44 (`01a11576-7e98-7090-8644-457d6af742db`) caducará sola hacia las
08:54 UTC. El Edificio Demo queda sin reservas.

**Qué no se tocó.** El servicio sigue en `locker-api-00001-g7z` con el 100 % del tráfico, el worker pool en
`locker-worker-00001-p2l` con 1 instancia, Cloud SQL `RUNNABLE` en `db-f1-micro` y cada secreto con su única versión.
Solo se usaron comandos de lectura (`describe`, `list`, `logging read`, `secrets versions access` y consultas `GET` a las
APIs de Cloud Run y Cloud Monitoring); el `gcloud` local no carga `run worker-pools` sin `grpc`, así que el worker
pool se consultó con un `GET` a la API REST de Cloud Run. Ninguna clave, secreto ni código de recogida aparece en este
documento ni en el repositorio.
