#!/usr/bin/env bash
# Borrado del despliegue de Locker API en Google Cloud (fase F7, docs/especificaciones.md §13.5).
# Borra lo que se factura (Cloud SQL, el servicio, el worker pool y el job), el mapeo del dominio propio (F7b) y los
# secretos. Con --unlink-billing, además desvincula la facturación del proyecto: así ya no se puede facturar nada.
# Nunca borra el proyecto, ni el dominio ni sus registros DNS (viven en Vercel y son del desarrollador).
#
# Se puede ejecutar varias veces: lo que ya no existe se salta.
# Uso: deploy/teardown.sh [--yes] [--unlink-billing]

# -e: para en el primer error; -u: una variable sin definir es un error; -o pipefail: falla la tubería si falla
# cualquiera de sus comandos, no solo el último
set -euo pipefail

# --- Configuración: los mismos nombres que setup.sh y el CD ---

PROJECT_ID="locker-api-cristian"
PROJECT_NUMBER="953827667605"
REGION="europe-west1"
GCLOUD_CONFIG="locker-api"

SQL_INSTANCE="locker-db"
API_SERVICE="locker-api"
WORKER_POOL="locker-worker"
MIGRATE_JOB="locker-migrate"
API_DOMAIN="api.lockerapi.dev"
SECRETS=(locker-api-keys locker-pickup-secret locker-db-url)

# --- Ayudantes ---

step() { printf '\n==> %s\n' "$1"; }
skip() { printf '    no existe: %s\n' "$1"; }
die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

# Comprueba que gcloud apunta a donde debe antes de borrar nada: la configuración activa, su proyecto y el número del
# proyecto. Un error aquí podría borrar recursos de otro proyecto de la cuenta
check_target() {
  local active configured number
  active=$(gcloud config configurations list --filter=is_active=true --format='value(name)')
  [[ $active == "$GCLOUD_CONFIG" ]] || die "la configuración activa de gcloud es «${active}», no «${GCLOUD_CONFIG}»"
  configured=$(gcloud config get-value project 2>/dev/null)
  [[ $configured == "$PROJECT_ID" ]] || die "la configuración «${GCLOUD_CONFIG}» apunta a «${configured}», no a «${PROJECT_ID}»"
  number=$(gcloud projects describe "$PROJECT_ID" --project="$PROJECT_ID" --format='value(projectNumber)')
  [[ $number == "$PROJECT_NUMBER" ]] || die "el proyecto ${PROJECT_ID} tiene el número «${number}», no ${PROJECT_NUMBER}"
}

# Comprueba que cada nombre de una lista es uno de los esperados. Si aparece un recurso que no es de F7, el script
# para sin borrar nada: puede ser de otra persona o de otra prueba, y eso lo decide el desarrollador.
# Los nombres pueden llegar como ruta completa (projects/.../workerPools/x): se compara solo el último trozo
only_expected() {
  local kind=$1 found=$2 name
  shift 2
  for name in $found; do
    name=${name##*/}
    [[ " $* " == *" ${name} "* ]] || die "${kind} «${name}» no es de F7: no se borra nada. Revísalo a mano"
  done
}

# --- Argumentos ---

ASSUME_YES=false
UNLINK_BILLING=false
for arg in "$@"; do
  case $arg in
    --yes) ASSUME_YES=true ;;
    --unlink-billing) UNLINK_BILLING=true ;;
    *) die "opción desconocida: ${arg}. Uso: deploy/teardown.sh [--yes] [--unlink-billing]" ;;
  esac
done

# --- 1. Comprobaciones previas ---

step "Comprobando la configuración de gcloud y el proyecto"
check_target
printf '    configuración %s, proyecto %s (%s), región %s\n' "$GCLOUD_CONFIG" "$PROJECT_ID" "$PROJECT_NUMBER" "$REGION"

# Borrar el worker pool necesita el módulo grpc en el Python de gcloud. Algunas instalaciones no lo traen (por
# ejemplo, gcloud de Homebrew usando otro Python). Se comprueba antes de borrar nada, para no dejarlo a medias
gcloud run worker-pools delete --help >/dev/null 2>&1 ||
  die "este gcloud no puede cargar «run worker-pools delete» (le falta grpc). Mira el README, «Despliegue en Google Cloud»"

# El mapeo del dominio propio está en la pista beta de gcloud: sin ese componente no se puede ver ni borrar
gcloud beta run domain-mappings --help >/dev/null 2>&1 ||
  die "falta el componente beta de gcloud, necesario para borrar el mapeo del dominio: gcloud components install beta"

# Lo que hay en el proyecto. Si una API ya está desactivada (o sin facturación) la lista falla: entonces no hay
# nada de ese tipo que borrar, y se sigue
step "Comprobando que todo lo que se va a borrar es de F7"
services=$(gcloud run services list --project="$PROJECT_ID" --region="$REGION" --format='value(metadata.name)' 2>/dev/null || true)
pools=$(gcloud run worker-pools list --project="$PROJECT_ID" --region="$REGION" --format='value(name)' 2>/dev/null || true)
jobs=$(gcloud run jobs list --project="$PROJECT_ID" --region="$REGION" --format='value(name)' 2>/dev/null || true)
instances=$(gcloud sql instances list --project="$PROJECT_ID" --format='value(name)' 2>/dev/null || true)
secrets=$(gcloud secrets list --project="$PROJECT_ID" --format='value(name)' 2>/dev/null || true)
mappings=$(gcloud beta run domain-mappings list --project="$PROJECT_ID" --region="$REGION" \
  --format='value(metadata.name)' 2>/dev/null || true)
only_expected "El servicio de Cloud Run" "$services" "$API_SERVICE"
only_expected "El worker pool" "$pools" "$WORKER_POOL"
only_expected "El job de Cloud Run" "$jobs" "$MIGRATE_JOB"
only_expected "La instancia de Cloud SQL" "$instances" "$SQL_INSTANCE"
only_expected "El secreto" "$secrets" "${SECRETS[@]}"
only_expected "El mapeo de dominio" "$mappings" "$API_DOMAIN"
printf '    solo hay recursos de F7\n'

if [[ $ASSUME_YES != true ]]; then
  read -r -p "Se van a BORRAR Cloud SQL (con sus datos), la API, su dominio, el worker, el job y los secretos. ¿Continuar? [s/N] " answer
  [[ $answer == "s" || $answer == "S" ]] || die "cancelado"
fi

# --- 2. Cómputo: primero lo que se conecta a la base de datos ---

step "Worker pool ${WORKER_POOL}"
if gcloud run worker-pools describe "$WORKER_POOL" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
  gcloud run worker-pools delete "$WORKER_POOL" --project="$PROJECT_ID" --region="$REGION" --quiet
else
  skip "$WORKER_POOL"
fi

# El mapeo de dominio apunta al servicio: se borra antes que él, para no dejar un mapeo huérfano
step "Mapeo de dominio ${API_DOMAIN}"
if gcloud beta run domain-mappings describe --domain="$API_DOMAIN" --project="$PROJECT_ID" --region="$REGION" \
  >/dev/null 2>&1; then
  gcloud beta run domain-mappings delete --domain="$API_DOMAIN" --project="$PROJECT_ID" --region="$REGION" --quiet
else
  skip "$API_DOMAIN"
fi

step "Servicio ${API_SERVICE}"
if gcloud run services describe "$API_SERVICE" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
  gcloud run services delete "$API_SERVICE" --project="$PROJECT_ID" --region="$REGION" --quiet
else
  skip "$API_SERVICE"
fi

step "Job ${MIGRATE_JOB}"
if gcloud run jobs describe "$MIGRATE_JOB" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
  gcloud run jobs delete "$MIGRATE_JOB" --project="$PROJECT_ID" --region="$REGION" --quiet
else
  skip "$MIGRATE_JOB"
fi

# --- 3. Cloud SQL: la pieza que más factura. Se pierden los datos (el despliegue es de demostración, A9) ---

step "Instancia de Cloud SQL ${SQL_INSTANCE}"
if gcloud sql instances describe "$SQL_INSTANCE" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud sql instances delete "$SQL_INSTANCE" --project="$PROJECT_ID" --quiet
else
  skip "$SQL_INSTANCE"
fi

# --- 4. Secretos: la próxima ejecución de setup.sh genera otros ---

step "Secretos"
for secret in "${SECRETS[@]}"; do
  if gcloud secrets describe "$secret" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud secrets delete "$secret" --project="$PROJECT_ID" --quiet
  else
    skip "$secret"
  fi
done

# --- 5. Facturación (opcional): sin cuenta vinculada, el proyecto no puede facturar nada ---

if [[ $UNLINK_BILLING == true ]]; then
  step "Desvinculando la facturación"
  billing_enabled=$(gcloud billing projects describe "$PROJECT_ID" --project="$PROJECT_ID" --format='value(billingEnabled)')
  if [[ $billing_enabled == "True" ]]; then
    gcloud billing projects unlink "$PROJECT_ID" --project="$PROJECT_ID" >/dev/null
    printf '    facturación desvinculada\n'
  else
    printf '    el proyecto ya no tenía facturación\n'
  fi
fi

# --- 6. Lo que queda: no se factura sin uso, y setup.sh lo reutiliza ---

step "Hecho. Quedan, sin coste mientras no se usen:"
cat <<'EOF'
    - el repositorio de Artifact Registry «locker», con las imágenes (unos cientos de MB)
    - las cuentas de servicio locker-runtime y locker-deployer, y sus permisos
    - la federación de identidad (pool locker-github y proveedor github)
    - el presupuesto «locker-api», en la cuenta de facturación
    - las APIs activadas
    - el dominio lockerapi.dev y sus registros DNS en Vercel (inofensivos: sin mapeo, api.lockerapi.dev no responde)
    Ojo: Cloud SQL no deja reutilizar el nombre «locker-db» hasta una semana después de borrarla.
EOF
