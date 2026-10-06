#!/usr/bin/env bash
# Preparación de Google Cloud para desplegar Locker API (fase F7, docs/especificaciones.md §13.5).
# Crea lo que no cambia entre despliegues: APIs, Artifact Registry, Cloud SQL, secretos, cuentas de servicio,
# federación de identidad con GitHub, permisos y presupuesto. El job, el servicio y el worker pool los crea el CD.
#
# Es idempotente: cada recurso se comprueba antes de crearse, así que una segunda ejecución no cambia ni duplica nada.
# Uso: deploy/setup.sh [--yes]     (--yes: sin pedir confirmación)

# -e: para en el primer error; -u: una variable sin definir es un error; -o pipefail: falla la tubería si falla
# cualquiera de sus comandos, no solo el último
set -euo pipefail

# --- Configuración: el único sitio con nombres. teardown.sh repite los mismos ---

# Proyecto y región. El número de proyecto sirve para comprobar que el id apunta al proyecto correcto
PROJECT_ID="locker-api-cristian"
PROJECT_NUMBER="953827667605"
REGION="europe-west1"

# Configuración de gcloud que debe estar activa (gcloud config configurations activate locker-api)
GCLOUD_CONFIG="locker-api"

# Repositorio de GitHub al que se le permite desplegar (la federación solo acepta tokens de este repositorio)
GITHUB_REPO="cristianrisueo/locker-api"

# Nombres de los recursos (tabla de recursos de §13.5)
AR_REPO="locker"
SQL_INSTANCE="locker-db"
DB_NAME="locker"
DB_USER="locker"
SECRET_API_KEYS="locker-api-keys"
SECRET_PICKUP="locker-pickup-secret"
SECRET_DB_URL="locker-db-url"
RUNTIME_SA="locker-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
DEPLOYER_SA="locker-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
WIF_POOL="locker-github"
WIF_PROVIDER="github"
BUDGET_NAME="locker-api"

# APIs que se activan: solo las necesarias.
# run (Cloud Run), sqladmin (Cloud SQL y su socket), secretmanager, artifactregistry (imágenes),
# iam (cuentas de servicio y federación), iamcredentials y sts (GitHub cambia su token por uno de Google),
# cloudresourcemanager (permisos del proyecto) y billingbudgets (el presupuesto)
APIS=(
  run.googleapis.com
  sqladmin.googleapis.com
  secretmanager.googleapis.com
  artifactregistry.googleapis.com
  iam.googleapis.com
  iamcredentials.googleapis.com
  sts.googleapis.com
  cloudresourcemanager.googleapis.com
  billingbudgets.googleapis.com
)

# --- Ayudantes ---

# Mensajes: un paso, un recurso que ya estaba, un aviso y un error que para el script
step() { printf '\n==> %s\n' "$1"; }
skip() { printf '    ya existe: %s\n' "$1"; }
warn() { printf 'AVISO: %s\n' "$1" >&2; }
die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

# Reintenta un comando hasta 5 veces, con 10 s entre intentos. Hace falta con los permisos: una cuenta de servicio
# recién creada tarda unos segundos en ser visible para IAM, y darle un rol al momento puede fallar
retry() {
  local attempt
  for attempt in 1 2 3 4 5; do
    "$@" && return 0
    warn "falló el intento ${attempt} de 5; se reintenta en 10 s"
    sleep 10
  done
  return 1
}

# Comprueba que gcloud apunta a donde debe antes de tocar nada: la configuración activa, su proyecto y el número del
# proyecto. Así un error de configuración nunca crea recursos en otro proyecto de la cuenta
check_target() {
  local active configured number
  active=$(gcloud config configurations list --filter=is_active=true --format='value(name)')
  [[ $active == "$GCLOUD_CONFIG" ]] || die "la configuración activa de gcloud es «${active}», no «${GCLOUD_CONFIG}»"
  configured=$(gcloud config get-value project 2>/dev/null)
  [[ $configured == "$PROJECT_ID" ]] || die "la configuración «${GCLOUD_CONFIG}» apunta a «${configured}», no a «${PROJECT_ID}»"
  number=$(gcloud projects describe "$PROJECT_ID" --project="$PROJECT_ID" --format='value(projectNumber)')
  [[ $number == "$PROJECT_NUMBER" ]] || die "el proyecto ${PROJECT_ID} tiene el número «${number}», no ${PROJECT_NUMBER}"
}

# ¿Existe el secreto? (describe falla si no existe; la salida no interesa)
secret_exists() { gcloud secrets describe "$1" --project="$PROJECT_ID" >/dev/null 2>&1; }

# Guarda un valor en Secret Manager: crea el secreto, o le añade una versión si ya existía.
# El valor entra por la entrada estándar (--data-file=-) con printf, que es un comando interno de bash: no pasa por
# ningún fichero ni aparece en la lista de procesos, y nunca se imprime
store_secret() {
  local name=$1 value=$2
  if secret_exists "$name"; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --project="$PROJECT_ID" --data-file=- >/dev/null
  else
    printf '%s' "$value" |
      gcloud secrets create "$name" --project="$PROJECT_ID" --replication-policy=automatic --data-file=- >/dev/null
  fi
  printf '    guardado en Secret Manager: %s\n' "$name"
}

# Da un rol en el proyecto a un miembro, solo si no lo tiene ya: así la segunda ejecución no reescribe la política.
# --condition=None: el rol se da sin condiciones (y gcloud no pregunta)
grant_project_role() {
  local member=$1 role=$2 current
  current=$(gcloud projects get-iam-policy "$PROJECT_ID" --project="$PROJECT_ID" \
    --flatten='bindings[].members' --filter="bindings.role='${role}' AND bindings.members='${member}'" \
    --format='value(bindings.role)')
  if [[ -n $current ]]; then
    skip "${role} para ${member}"
    return
  fi
  retry gcloud projects add-iam-policy-binding "$PROJECT_ID" --project="$PROJECT_ID" \
    --member="$member" --role="$role" --condition=None --quiet >/dev/null
  printf '    rol concedido: %s para %s\n' "$role" "$member"
}

# Lo mismo, pero sobre una cuenta de servicio concreta (quién puede actuar como ella), no sobre todo el proyecto
grant_sa_role() {
  local sa=$1 member=$2 role=$3 current
  current=$(gcloud iam service-accounts get-iam-policy "$sa" --project="$PROJECT_ID" \
    --flatten='bindings[].members' --filter="bindings.role='${role}' AND bindings.members='${member}'" \
    --format='value(bindings.role)')
  if [[ -n $current ]]; then
    skip "${role} sobre ${sa} para ${member}"
    return
  fi
  retry gcloud iam service-accounts add-iam-policy-binding "$sa" --project="$PROJECT_ID" \
    --member="$member" --role="$role" --quiet >/dev/null
  printf '    rol concedido: %s sobre %s para %s\n' "$role" "$sa" "$member"
}

# Crea una cuenta de servicio si no existe
ensure_service_account() {
  local email=$1 display=$2
  if gcloud iam service-accounts describe "$email" --project="$PROJECT_ID" >/dev/null 2>&1; then
    skip "$email"
  else
    gcloud iam service-accounts create "${email%%@*}" --project="$PROJECT_ID" --display-name="$display"
  fi
}

# --- Argumentos ---

ASSUME_YES=false
for arg in "$@"; do
  case $arg in
    --yes) ASSUME_YES=true ;;
    *) die "opción desconocida: ${arg}. Uso: deploy/setup.sh [--yes]" ;;
  esac
done

# --- 1. Comprobaciones previas: proyecto correcto y facturación vinculada ---

step "Comprobando la configuración de gcloud y el proyecto"
check_target
printf '    configuración %s, proyecto %s (%s), región %s\n' "$GCLOUD_CONFIG" "$PROJECT_ID" "$PROJECT_NUMBER" "$REGION"

# Sin facturación no se puede crear casi nada, y el script no la vincula: eso lo decide el desarrollador
step "Comprobando la facturación"
billing_enabled=$(gcloud billing projects describe "$PROJECT_ID" --project="$PROJECT_ID" --format='value(billingEnabled)')
[[ $billing_enabled == "True" ]] ||
  die "el proyecto no tiene facturación vinculada. Vincúlala con: gcloud billing projects link ${PROJECT_ID} --billing-account=<id>"
billing_account=$(gcloud billing projects describe "$PROJECT_ID" --project="$PROJECT_ID" --format='value(billingAccountName)')
billing_account=${billing_account#billingAccounts/}
printf '    facturación vinculada a la cuenta %s\n' "$billing_account"

if [[ $ASSUME_YES != true ]]; then
  read -r -p "Se van a crear recursos que se facturan (sobre todo Cloud SQL). ¿Continuar? [s/N] " answer
  [[ $answer == "s" || $answer == "S" ]] || die "cancelado"
fi

# --- 2. APIs ---

step "Activando las APIs necesarias"
enabled=$(gcloud services list --enabled --project="$PROJECT_ID" --format='value(config.name)')
missing=()
for api in "${APIS[@]}"; do
  if grep -qx "$api" <<<"$enabled"; then
    skip "$api"
  else
    missing+=("$api")
  fi
done
if ((${#missing[@]} > 0)); then
  gcloud services enable "${missing[@]}" --project="$PROJECT_ID"
fi

# --- 3. Artifact Registry: el repositorio Docker de las imágenes ---

step "Repositorio de imágenes (Artifact Registry)"
if gcloud artifacts repositories describe "$AR_REPO" --project="$PROJECT_ID" --location="$REGION" >/dev/null 2>&1; then
  skip "$AR_REPO"
else
  gcloud artifacts repositories create "$AR_REPO" --project="$PROJECT_ID" --location="$REGION" \
    --repository-format=docker --description="Imágenes de Locker API (etiqueta = SHA del commit)"
fi

# --- 4. Cloud SQL: instancia, base de datos y usuario ---

step "Instancia de Cloud SQL (tarda varios minutos la primera vez)"
if gcloud sql instances describe "$SQL_INSTANCE" --project="$PROJECT_ID" >/dev/null 2>&1; then
  skip "$SQL_INSTANCE"
else
  # La más barata (A26): Enterprise con el tier compartido db-f1-micro, 10 GB SSD que no crecen solos, zonal (sin
  # alta disponibilidad) y con IP pública pero sin redes autorizadas: solo se llega por el socket de Cloud SQL, que
  # autoriza con IAM (cloudsql.client). Sin protección contra el borrado, para que teardown.sh pueda borrarla
  gcloud sql instances create "$SQL_INSTANCE" --project="$PROJECT_ID" --region="$REGION" \
    --database-version=POSTGRES_18 --edition=enterprise --tier=db-f1-micro \
    --storage-type=SSD --storage-size=10GB --no-storage-auto-increase \
    --availability-type=zonal --assign-ip --no-deletion-protection
fi

# Si una ejecución anterior se cortó mientras se creaba, espera a que la instancia esté lista (como mucho 20 minutos)
for _ in $(seq 1 120); do
  state=$(gcloud sql instances describe "$SQL_INSTANCE" --project="$PROJECT_ID" --format='value(state)')
  [[ $state == "RUNNABLE" ]] && break
  printf '    estado de la instancia: %s; se espera 10 s\n' "$state"
  sleep 10
done
[[ $state == "RUNNABLE" ]] || die "la instancia ${SQL_INSTANCE} no está lista (estado ${state})"

step "Base de datos y usuario"
if gcloud sql databases describe "$DB_NAME" --instance="$SQL_INSTANCE" --project="$PROJECT_ID" >/dev/null 2>&1; then
  skip "base de datos ${DB_NAME}"
else
  gcloud sql databases create "$DB_NAME" --instance="$SQL_INSTANCE" --project="$PROJECT_ID"
fi

# El usuario y el secreto con la URL van juntos: la contraseña solo se conoce al crearla. Si existen los dos, no se
# toca nada. Si falta el secreto (por ejemplo, se borró con teardown.sh pero la instancia sigue), se genera otra
# contraseña, se le pone al usuario y se guarda la URL nueva
user_exists=$(gcloud sql users list --instance="$SQL_INSTANCE" --project="$PROJECT_ID" \
  --filter="name=${DB_USER}" --format='value(name)')
if [[ -n $user_exists ]] && secret_exists "$SECRET_DB_URL"; then
  skip "usuario ${DB_USER} y secreto ${SECRET_DB_URL}"
else
  # Contraseña aleatoria alfanumérica: 24 bytes en hexadecimal, 48 caracteres. Sin símbolos, así no hay que escaparla
  # en la URL. gcloud la recibe como argumento (no tiene otra forma no interactiva): vive un instante en la lista de
  # procesos de esta máquina, y nunca se imprime
  db_password=$(openssl rand -hex 24)
  if [[ -n $user_exists ]]; then
    gcloud sql users set-password "$DB_USER" --instance="$SQL_INSTANCE" --project="$PROJECT_ID" \
      --password="$db_password" >/dev/null
  else
    gcloud sql users create "$DB_USER" --instance="$SQL_INSTANCE" --project="$PROJECT_ID" \
      --password="$db_password" >/dev/null
  fi
  # La URL entra por el socket de Cloud SQL: sin host ni puerto, y el directorio del socket en ?host=.
  # Cloud Run monta ese directorio en /cloudsql/<proyecto>:<región>:<instancia> (--add-cloudsql-instances)
  store_secret "$SECRET_DB_URL" \
    "postgresql+asyncpg://${DB_USER}:${db_password}@/${DB_NAME}?host=/cloudsql/${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"
  unset db_password
fi

# --- 5. Secretos de la aplicación ---

step "Secretos de la aplicación (Secret Manager)"
# Claves de API: una de operador y una del transportista SEUR, aleatorias (48 caracteres; la API exige 16 como
# mínimo y F7 pide 32). Solo se generan si el secreto no existe: una segunda ejecución no las cambia (A29)
if secret_exists "$SECRET_API_KEYS"; then
  skip "$SECRET_API_KEYS"
else
  operator_key=$(openssl rand -hex 24)
  seur_key=$(openssl rand -hex 24)
  # JSON de una línea, como pide API_KEYS (§12.1)
  store_secret "$SECRET_API_KEYS" \
    "$(printf '[{"key":"%s","role":"operator"},{"key":"%s","role":"carrier","name":"SEUR"}]' "$operator_key" "$seur_key")"
  unset operator_key seur_key
fi

# Secreto del código de recogida: 32 bytes en hexadecimal, 64 caracteres (la API exige 32 como mínimo)
if secret_exists "$SECRET_PICKUP"; then
  skip "$SECRET_PICKUP"
else
  store_secret "$SECRET_PICKUP" "$(openssl rand -hex 32)"
fi

# --- 6. Cuentas de servicio y permisos ---

step "Cuentas de servicio"
# locker-runtime: la identidad con la que se ejecutan la API, el worker y el job de migraciones
ensure_service_account "$RUNTIME_SA" "Locker API: ejecución (Cloud Run)"
# locker-deployer: la identidad con la que despliega GitHub Actions
ensure_service_account "$DEPLOYER_SA" "Locker API: despliegue (GitHub Actions)"

step "Permisos de locker-runtime: solo leer secretos y conectarse a Cloud SQL"
grant_project_role "serviceAccount:${RUNTIME_SA}" roles/secretmanager.secretAccessor
grant_project_role "serviceAccount:${RUNTIME_SA}" roles/cloudsql.client

step "Permisos de locker-deployer: publicar la imagen y desplegar"
# Subir imágenes al repositorio de Artifact Registry
grant_project_role "serviceAccount:${DEPLOYER_SA}" roles/artifactregistry.writer
# Desplegar el servicio, el worker pool y el job, y ejecutar el job. Es run.admin y no run.developer porque el
# servicio es público (--allow-unauthenticated): eso es dar el rol de invocador a allUsers, y cambiar la política IAM
# del servicio solo lo permite run.admin
grant_project_role "serviceAccount:${DEPLOYER_SA}" roles/run.admin
# Desplegar «como» locker-runtime: se concede sobre esa cuenta, no sobre todo el proyecto
grant_sa_role "$RUNTIME_SA" "serviceAccount:${DEPLOYER_SA}" roles/iam.serviceAccountUser

# --- 7. Federación de identidad: GitHub Actions entra sin claves de cuenta de servicio ---

step "Federación de identidad con GitHub (Workload Identity Federation)"
if gcloud iam workload-identity-pools describe "$WIF_POOL" --project="$PROJECT_ID" --location=global >/dev/null 2>&1; then
  skip "pool ${WIF_POOL}"
else
  gcloud iam workload-identity-pools create "$WIF_POOL" --project="$PROJECT_ID" --location=global \
    --display-name="GitHub Actions"
fi

# Proveedor OIDC: acepta los tokens que firma GitHub Actions para cada ejecución. attribute-mapping copia el
# repositorio del token a un atributo, y attribute-condition rechaza cualquier token que no venga de este repositorio:
# sin ella, cualquier repositorio de GitHub podría pedir credenciales a este pool
if gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER" --project="$PROJECT_ID" --location=global \
  --workload-identity-pool="$WIF_POOL" >/dev/null 2>&1; then
  skip "proveedor ${WIF_PROVIDER}"
else
  gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" --project="$PROJECT_ID" \
    --location=global --workload-identity-pool="$WIF_POOL" --display-name="GitHub OIDC" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}'"
fi

# Solo las identidades de este repositorio pueden actuar como locker-deployer
WIF_POOL_PATH="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}"
grant_sa_role "$DEPLOYER_SA" "principalSet://iam.googleapis.com/${WIF_POOL_PATH}/attribute.repository/${GITHUB_REPO}" \
  roles/iam.workloadIdentityUser

# --- 8. Presupuesto: avisa por correo al 50, 90 y 100 % de 5 EUR ---

step "Presupuesto de 5 EUR"
# Un presupuesto avisa, no corta el gasto. Vive en la cuenta de facturación (filtrado a este proyecto) y pide
# permisos sobre ella: si falla, se avisa y se sigue, no es imprescindible para desplegar
if ! budgets=$(gcloud billing budgets list --billing-account="$billing_account" --project="$PROJECT_ID" \
  --filter="displayName=${BUDGET_NAME}" --format='value(name)'); then
  warn "no se pudo consultar los presupuestos (¿permisos sobre la cuenta de facturación?)"
elif [[ -n $budgets ]]; then
  skip "presupuesto ${BUDGET_NAME}"
elif ! gcloud billing budgets create --billing-account="$billing_account" --project="$PROJECT_ID" \
  --display-name="$BUDGET_NAME" --budget-amount=5EUR --calendar-period=month \
  --filter-projects="projects/${PROJECT_NUMBER}" \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0 >/dev/null; then
  warn "no se pudo crear el presupuesto; créalo a mano en la consola si lo quieres"
else
  printf '    presupuesto creado: %s\n' "$BUDGET_NAME"
fi

# --- 9. Variables para GitHub (no son secretos) ---

step "Hecho. Variables del repositorio de GitHub (no son secretos):"
cat <<EOF
    GCP_PROJECT_ID=${PROJECT_ID}
    GCP_REGION=${REGION}
    GCP_WIF_PROVIDER=${WIF_POOL_PATH}/providers/${WIF_PROVIDER}
    GCP_DEPLOYER_SA=${DEPLOYER_SA}

Créalas con:
    gh variable set GCP_PROJECT_ID --repo ${GITHUB_REPO} --body ${PROJECT_ID}
    gh variable set GCP_REGION --repo ${GITHUB_REPO} --body ${REGION}
    gh variable set GCP_WIF_PROVIDER --repo ${GITHUB_REPO} --body ${WIF_POOL_PATH}/providers/${WIF_PROVIDER}
    gh variable set GCP_DEPLOYER_SA --repo ${GITHUB_REPO} --body ${DEPLOYER_SA}
EOF
